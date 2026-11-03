"""镜像在线构建编排: 生成 buildspec → 打 zip 传 S3 → 幂等建 ws ECR repo →
StartBuild → 写 DDB。状态回收 + 自动注册见下半部分 (reconcile)。

权限 = 任何 ws 成员 (复用 images 的 _require_ws_member)。用户只写 Dockerfile,
buildspec 由平台生成。build 成功产出的镜像自动注册进镜像中心 (source=built)。
"""

from __future__ import annotations

import io
import uuid as _uuid
import zipfile
from typing import Any

from fastapi import HTTPException, status

from app.adapters.aws import codebuild, ecr, s3_upload
from app.adapters.ddb import tables
from app.core.config import get_settings
from app.core.i18n import t
from app.modules.registry.api.schemas import RegisterImageBody, SubmitBuildBody
from app.modules.registry.orchestration import images as images_svc
from app.modules.registry.orchestration.images import _require_ws_member, _username
from app.repositories import image_builds as repo

# 平台生成的 buildspec: 登录 ECR → docker build → push。ECR_URI/IMAGE_TAG 由
# StartBuild 的 env override 传入。
# DLC_ACCOUNT: AWS Deep Learning Container 官方镜像所在账号 (公开固定, 各 region 同号)。
# 用户 Dockerfile 常 FROM 它 (如 pytorch-training), 跨账号私有 ECR 需单独登录才能拉,
# 否则 docker build 拉 base 报 401。这里 pre_build 顺带登录 DLC registry。
_DLC_ACCOUNT = "763104351884"

_BUILDSPEC = f"""version: 0.2
phases:
  pre_build:
    commands:
      - PW=$(aws ecr get-login-password --region $AWS_DEFAULT_REGION)
      # Log in to the target registry (own account, for push) and the DLC source account (for pulling official DLC base images in FROM)
      - echo "$PW" | docker login --username AWS --password-stdin $ECR_URI
      - echo "$PW" | docker login --username AWS --password-stdin {_DLC_ACCOUNT}.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com
  build:
    commands:
      - docker build -t $ECR_URI:$IMAGE_TAG .
  post_build:
    commands:
      - docker push $ECR_URI:$IMAGE_TAG
"""


# ECR repo 名总长上限 (AWS 硬限)。
_ECR_REPO_MAX = 256


def _repo_name(image_name: str) -> str:
    """ECR repo 名 = 用户直接输入的镜像名 (期望形如 namespace/repo-name)。

    不再由平台加前缀; 用户自定, 支持路径式 (含 /)。schemas 已按 ECR repo 规范
    校验 image_name 合规 (小写, 段用 . _ - 分隔, / 分路径)。IAM push scope 相应
    放开到 repository/* (见 codebuild_construct)。
    """
    return image_name.lower()


def _split_name_tag(target_tag: str) -> tuple[str, str]:
    """拆 name:tag → (image_name, tag)。schemas 已按正则校验格式, 这里只拆分。

    name 可含 / (路径式 repo), 故按最后一个 : 拆 (tag 不含 :)。
    """
    name, _, tag = target_tag.rpartition(":")
    return name, tag


def _make_zip(dockerfile: str, buildspec: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Dockerfile", dockerfile)
        z.writestr("buildspec.yml", buildspec)
    return buf.getvalue()


def _to_item(sort_key: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": sort_key.rsplit("#", 1)[-1],
        "status": row.get("status") or "building",
        "target_tag": row.get("target_tag") or "",
        "target_uri": row.get("target_uri") or "",
        "uses": list(row.get("uses") or []),
        "compute_type": row.get("compute_type") or "",
        "timeout_minutes": int(row.get("timeout_minutes") or 120),
        "dockerfile": row.get("dockerfile") or "",
        "logs_url": row.get("logs_url") or "",
        "codebuild_id": row.get("codebuild_id") or "",
        "creator_username": row.get("creator_username") or "",
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
    }


async def submit_build(
    workspace_id: str, body: SubmitBuildBody, user: dict[str, Any]
) -> dict[str, Any]:
    await _require_ws_member(workspace_id, user)
    settings = get_settings()
    if not settings.codebuild_project_name or not settings.image_build_source_bucket:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, t("registry.build_disabled")
        )

    build_id = _uuid.uuid4().hex[:12]
    # repo 名 = 用户输入的镜像名原文 (期望 namespace/repo-name); tag 作镜像标签
    # (name:tag 已按 schema 校验合规)
    image_name, image_tag = _split_name_tag(body.target_tag)
    repo_name = _repo_name(image_name)
    if len(repo_name) > _ECR_REPO_MAX:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            t("registry.repo_name_too_long", length=len(repo_name), max=_ECR_REPO_MAX, repo_name=repo_name),
        )

    # 1. 幂等建 ws ECR repo, 拿完整 repositoryUri
    repo_uri = await ecr.ensure_repository(repo_name)
    # target_uri submit 时算好存 DDB, 回收时直接读, 不重取 (避免多一次 ECR 调用)
    target_uri = f"{repo_uri}:{image_tag}"

    # 2. 打包 Dockerfile+buildspec → S3
    zip_key = f"builds/{workspace_id}/{build_id}.zip"
    await s3_upload.put_bytes(
        settings.image_build_source_bucket,
        zip_key,
        _make_zip(body.dockerfile, _BUILDSPEC),
    )

    # 3. StartBuild
    cb_id = await codebuild.start_build(
        project=settings.codebuild_project_name,
        source_zip_key=zip_key,
        compute_type=body.compute_type,
        ecr_uri=repo_uri,
        image_tag=image_tag,
        timeout_minutes=body.timeout_minutes,
    )

    # 4. 写 DDB (building)
    sk = tables.image_build_key(build_id)
    row = await repo.put(
        workspace_id=workspace_id,
        sort_key=sk,
        item_fields={
            "status": "building",
            "dockerfile": body.dockerfile,
            "target_repo": repo_name,
            "target_tag": body.target_tag,
            "target_uri": target_uri,
            "uses": list(body.uses),
            "compute_type": body.compute_type,
            "timeout_minutes": body.timeout_minutes,
            "codebuild_id": cb_id,
            "logs_url": "",
            "registered_image_id": "",
            "creator_username": _username(user),
        },
    )
    return _to_item(sk, row)


def _strip(row: dict[str, Any]) -> dict[str, Any]:
    """去掉 repo.put 会重设的 key (回收更新时保留其余字段)。"""
    return {
        k: v
        for k, v in row.items()
        if k not in ("workspace_id", "sort_key", "created_at", "updated_at")
    }


async def _reconcile_building(
    workspace_id: str, rows: list[dict[str, Any]], user: dict[str, Any]
) -> None:
    """对 status=building 的记录查 CodeBuild, 更新终态; 成功则自动注册镜像。"""
    building = [
        r for r in rows if r.get("status") == "building" and r.get("codebuild_id")
    ]
    if not building:
        return
    id_map = {r["codebuild_id"]: r for r in building}
    try:
        cb_builds = await codebuild.batch_get_builds(list(id_map.keys()))
    except Exception as exc:  # noqa: BLE001 - 回收失败不阻塞列表, 下次再查
        from app.core.logging import get_logger

        get_logger(__name__).info("image_build.reconcile_skip", err=str(exc))
        return

    for cb in cb_builds:
        r = id_map.get(cb.get("id"))
        if r is None:
            continue
        st = cb.get("buildStatus")
        if st == "IN_PROGRESS":
            continue
        logs_url = (cb.get("logs") or {}).get("deepLink") or ""
        sk = r["sort_key"]
        if st == "SUCCEEDED":
            # target_uri 在 submit 时已存好, 直接用
            reg = await images_svc.register_image(
                workspace_id,
                RegisterImageBody(
                    image_uri=r.get("target_uri", ""),
                    display_name=r.get("target_tag", ""),
                    uses=list(r.get("uses") or []),
                    source="built",
                ),
                user,
            )
            await repo.put(
                workspace_id=workspace_id,
                sort_key=sk,
                item_fields={
                    **_strip(r),
                    "status": "success",
                    "logs_url": logs_url,
                    "registered_image_id": reg["id"],
                },
            )
        else:  # FAILED / TIMED_OUT / STOPPED / FAULT
            await repo.put(
                workspace_id=workspace_id,
                sort_key=sk,
                item_fields={**_strip(r), "status": "failed", "logs_url": logs_url},
            )


async def list_builds(
    workspace_id: str, user: dict[str, Any]
) -> list[dict[str, Any]]:
    await _require_ws_member(workspace_id, user)
    rows = await repo.list_all(workspace_id)
    await _reconcile_building(workspace_id, rows, user)
    rows = await repo.list_all(workspace_id)  # 回收后重读拿最新状态
    items = [_to_item(r["sort_key"], r) for r in rows]
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items


async def get_build(
    workspace_id: str, build_id: str, user: dict[str, Any]
) -> dict[str, Any]:
    await _require_ws_member(workspace_id, user)
    sk = tables.image_build_key(build_id)
    row = await repo.get(workspace_id, sk)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("registry.build_not_found"))
    await _reconcile_building(workspace_id, [row], user)
    row = await repo.get(workspace_id, sk) or row
    return _to_item(sk, row)


async def get_build_logs(
    workspace_id: str, build_id: str, user: dict[str, Any],
    next_token: str | None = None,
) -> dict[str, Any]:
    """返回 CloudWatch 日志文本 + log group + region + 控制台链接 + 翻页 token。

    next_token: 前端"加载更多"传上次返回的 next_token 续拉下一页;
    返回的 next_token 为空表示已到末尾。
    """
    await _require_ws_member(workspace_id, user)
    sk = tables.image_build_key(build_id)
    row = await repo.get(workspace_id, sk)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("registry.build_not_found"))
    cb_id = row.get("codebuild_id") or ""
    if cb_id:
        log_text, tok = await codebuild.get_build_log_text(cb_id, next_token=next_token)
    else:
        log_text, tok = "", None
    region = get_settings().aws_region
    # log group 从 codebuild_id ('proj:uuid') 的 proj 段拼: /aws/codebuild/<proj>
    project = cb_id.partition(":")[0]
    log_group = f"/aws/codebuild/{project}" if project else ""
    # 后端已有的 deepLink (回收时写) 优先; 没有则前端可用 log_group+region 自拼
    return {
        "log_text": log_text,
        "log_group": log_group,
        "region": region,
        "logs_url": row.get("logs_url", ""),
        "next_token": tok or "",
    }
