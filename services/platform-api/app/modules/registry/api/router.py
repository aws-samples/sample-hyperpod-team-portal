"""Registry HTTP routes — ECR repos dropdown 数据源.

只读端点, 无 DDB 落地, 直接走 AWS API. 用于训练/推理任务创建表单的镜像选择.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.adapters.aws import ecr
from app.core.security import get_current_user
from app.modules.registry.api.schemas import (
    ImageBuildItem,
    RegisterImageBody,
    SubmitBuildBody,
    WorkspaceImageItem,
)
from app.modules.registry.orchestration import builds as builds_svc
from app.modules.registry.orchestration import images as images_svc

registry_router = APIRouter(tags=["registry"])


# ----- ECR -----

@registry_router.get(
    "/registry/ecr/repos",
    summary="列 ECR 仓库 (镜像下拉源)",
    description=(
        "直连 AWS ECR `DescribeRepositories`, 返平台账号下所有可见仓库 (无 ws 隔离).\n\n"
        "**用途**: 前端在**注册工作空间镜像**表单里选仓库 (第一步), 选完再列 tag.\n"
        "**权限**: 所有登录用户可读. 无 DDB 落地."
    ),
    responses={
        401: {"description": "未登录"},
        500: {"description": "ECR API 调用失败 (异常未捕获, 统一 500)"},
    },
)
async def list_ecr_repos_endpoint(
    max_results: int = Query(default=100, ge=1, le=500),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await ecr.list_repositories(max_results=max_results)


@registry_router.get(
    "/registry/ecr/repos/{repo_name:path}/tags",
    summary="列指定 ECR 仓库的 image tag",
    description=(
        "直连 ECR `DescribeImages`, 返指定 repo 的 tag 列表 (含 digest / pushed_at).\n\n"
        "`repo_name` 支持带 `/` (path 参数), e.g. `team/train`. 无 tag 的 manifest 被过滤.\n\n"
        "**权限**: 所有登录用户可读. 无 DDB 落地.\n"
        "**注意**: 列举过程的**任何异常**都被统一包成 404 (含权限 / 限流等), 非仅 repo 不存在."
    ),
    responses={
        401: {"description": "未登录"},
        404: {"description": "ECR 仓库不存在, 或列举过程任何失败"},
    },
)
async def list_ecr_tags_endpoint(
    repo_name: str,
    max_results: int = Query(default=50, ge=1, le=200),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    try:
        return await ecr.list_image_tags(repo_name, max_results=max_results)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ECR repo not found or list failed: {repo_name} ({exc})",
        ) from exc


# ----- 镜像中心 (工作空间镜像注册 · 引用模型, 落 DDB WorkspaceImages) -----
# 任何 ws 成员可注册/列/删; 创建开发机/训练/推理时按 uses 筛选选用。

@registry_router.get(
    "/workspaces/{ws_id}/images",
    response_model=list[WorkspaceImageItem],
    summary="列本工作空间已注册镜像",
    description=(
        "读 DDB `WorkspaceImages`, 返本 ws 全部注册镜像 (含 `uses` 标签 / 显示名 / ECR URI / 来源), "
        "按 `created_at` 倒序 (最近注册在前).\n\n"
        "**用途**: 创建开发机 / 训练 / 推理表单按 `uses` ∈ {`dev`, `training`, `inference`} 过滤镜像下拉源.\n"
        "**权限**: ws 成员或平台超管. ws 不存在时按 **403** 返."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员且非超管 (含 ws 不存在)"},
    },
)
async def list_workspace_images(
    ws_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[WorkspaceImageItem]:
    rows = await images_svc.list_images(ws_id, current_user)
    return [WorkspaceImageItem(**r) for r in rows]


@registry_router.post(
    "/workspaces/{ws_id}/images",
    response_model=WorkspaceImageItem,
    status_code=status.HTTP_201_CREATED,
    summary="注册镜像引用到本 ws",
    description=(
        "把已存在的 ECR 镜像 URI 登记到本 ws 的镜像库, 打上 `uses` "
        "(多选, ∈ {`dev`, `training`, `inference`}) 分类标签.\n\n"
        "- 只是**引用**, 不复制 / 不动 ECR 镜像本体; **也不二次校验 URI 在 ECR 真存在**\n"
        "- 后续创建任务时按 uses + ws 筛选可见范围\n"
        "- `display_name` 留空则取 URI 末段兜底\n"
        "- **不做去重**: 同一 URI 可重复注册, 每次生成新 `id`\n\n"
        "**权限**: ws 成员或平台超管. ws 不存在时按 **403** 返."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员且非超管 (含 ws 不存在)"},
        422: {"description": "image_uri 长度 / uses 空或含非法枚举 / source 非法"},
    },
)
async def register_workspace_image(
    ws_id: str,
    payload: RegisterImageBody,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> WorkspaceImageItem:
    row = await images_svc.register_image(ws_id, payload, current_user)
    return WorkspaceImageItem(**row)


@registry_router.delete(
    "/workspaces/{ws_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="取消注册镜像引用",
    description=(
        "从本 ws 的镜像库移除该引用条目. **仅删 DDB 引用, 不动 ECR 镜像本体**.\n\n"
        "**权限**: ws 成员或平台超管. **幂等**: 删不存在 / 已删的也返 204."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员且非超管 (含 ws 不存在)"},
    },
)
async def unregister_workspace_image(
    ws_id: str,
    image_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> None:
    await images_svc.unregister_image(ws_id, image_id, current_user)


# ----- 镜像在线构建 (Dockerfile → CodeBuild → 自动注册) -----

@registry_router.post(
    "/workspaces/{ws_id}/image-builds",
    response_model=ImageBuildItem,
    status_code=status.HTTP_201_CREATED,
    summary="提交在线镜像构建",
    description=(
        "把 Dockerfile 提交给 AWS CodeBuild 打包成镜像, 构建成功后**自动注册**到本 ws 镜像库.\n\n"
        "- `target_tag` 形如 `namespace/repo-name:v1`; 冒号左侧是 **ECR repo 原文** "
        "(平台不再加 `hp-<ns>-` 前缀, 用户自定命名 2026-07-24). repo 段须符合 ECR 规范: "
        "小写字母/数字开头, `.` `_` `-` 单字符分隔, `/` 分路径, 不允许大写/连续分隔符/首尾分隔符\n"
        "- 幂等建 ECR repo → 打包 Dockerfile + 平台生成的 buildspec 传 S3 → StartBuild → "
        "落 DDB `WorkspaceImageBuilds` (`status`=`building`)\n"
        "- 状态由后续 GET / list 端点触发的回收器推进 (`building` → `success` / `failed`)\n"
        "- 只传 Dockerfile 文本, 不支持 COPY 本地文件; `timeout_minutes` 5-480 (默认 120)\n\n"
        "**权限**: ws 成员或平台超管. ws 不存在时按 **403** 返."
    ),
    responses={
        400: {"description": "镜像在线构建未启用 (CodeBuild / S3 源桶未配置); 或 ECR repo 名超 256 字符"},
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员且非超管 (含 ws 不存在)"},
        422: {"description": "Dockerfile 空 / 超 64KB; target_tag 不符 name:tag 正则; uses 空或非法"},
        500: {"description": "ECR 建 repo / S3 上传 / CodeBuild StartBuild 失败 (统一 500)"},
    },
)
async def submit_image_build(
    ws_id: str,
    payload: SubmitBuildBody,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> ImageBuildItem:
    row = await builds_svc.submit_build(ws_id, payload, current_user)
    return ImageBuildItem(**row)


@registry_router.get(
    "/workspaces/{ws_id}/image-builds",
    response_model=list[ImageBuildItem],
    summary="列本 ws 镜像构建历史",
    description=(
        "读 DDB `WorkspaceImageBuilds`, 返本 ws 全部构建记录 (`status` ∈ "
        "{`building`, `success`, `failed`} / target_tag / target_uri / 提交人 / 日志链接), "
        "按 `created_at` 倒序.\n\n"
        "**副作用**: 读取时会**触发状态回收器** — 对 `building` 记录批量查 CodeBuild, 落终态到 DDB "
        "(In-place, 无独立 informer); 构建成功的还会**自动注册镜像**进本 ws 镜像库 (source=`built`). "
        "回收本身失败会静默跳过 (不影响列表返回, 下次读再试).\n\n"
        "**权限**: ws 成员或平台超管. ws 不存在时按 **403** 返."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员且非超管 (含 ws 不存在)"},
    },
)
async def list_image_builds(
    ws_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[ImageBuildItem]:
    rows = await builds_svc.list_builds(ws_id, current_user)
    return [ImageBuildItem(**r) for r in rows]


@registry_router.get(
    "/workspaces/{ws_id}/image-builds/{build_id}",
    response_model=ImageBuildItem,
    summary="查询单个构建详情",
    description=(
        "读 DDB 单条构建记录. **副作用**: 该记录若仍是 `building`, 触发状态回收器同步 CodeBuild 最新 "
        "`status` (成功则自动注册镜像); 回收失败静默跳过, 返回上次已知状态.\n\n"
        "**权限**: ws 成员或平台超管. ws 不存在时按 **403** 返."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员且非超管 (含 ws 不存在)"},
        404: {"description": "构建记录不存在或不属于本 ws"},
    },
)
async def get_image_build(
    ws_id: str,
    build_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> ImageBuildItem:
    row = await builds_svc.get_build(ws_id, build_id, current_user)
    return ImageBuildItem(**row)


@registry_router.get(
    "/workspaces/{ws_id}/image-builds/{build_id}/logs",
    summary="获取构建日志 (文本 + 链接, 支持翻页)",
    description=(
        "返 CodeBuild 该次构建的 CloudWatch 日志**文本**及定位信息: "
        "`{log_text, log_group, region, logs_url, next_token}`, 供前端内嵌查看或跳控制台排查失败原因.\n\n"
        "- `next_token`: 传上次返回的值续拉下一页 (**加载更多**); 返回空串表示已到末尾\n"
        "- 记录还没有 `codebuild_id` 时返空 `log_text` (不 404)\n\n"
        "**权限**: ws 成员或平台超管. ws 不存在时按 **403** 返."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员且非超管 (含 ws 不存在)"},
        404: {"description": "构建记录不存在或不属于本 ws"},
        500: {"description": "CloudWatch Logs 拉取失败 (统一 500)"},
    },
)
async def get_image_build_logs(
    ws_id: str,
    build_id: str,
    next_token: str | None = None,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    return await builds_svc.get_build_logs(
        ws_id, build_id, current_user, next_token=next_token or None
    )


# NOTE: 原 S3 buckets/objects + K8s PVC 三个端点已删 (2026-06-14):
# - S3 列举前端无人调用 (workspace S3 挂载走 /workspaces/{ws_id}/s3, 带成员闸门)
# - PVC 列举被 /workspaces/{ws_id}/shared-pvcs (带成员闸门) 取代, 前端已无人调用
# 它们无 ws 隔离 (传任意 bucket/namespace 即可越权读别队数据), 且是死代码, 故删。
