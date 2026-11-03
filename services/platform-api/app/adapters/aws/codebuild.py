"""CodeBuild adapter (aioboto3) · 触发镜像构建 + 查状态。

用户只写 Dockerfile, 平台生成 buildspec 打包传 S3。StartBuild 用
sourceLocationOverride 指向本次 build 的 zip, computeTypeOverride 用用户选的规格,
env override 传 ECR_URI / IMAGE_TAG 给 buildspec。
"""

from __future__ import annotations

from typing import Any

import aioboto3

from app.core.config import get_settings


def _session() -> aioboto3.Session:
    s = get_settings()
    return (
        aioboto3.Session(profile_name=s.aws_profile)
        if s.aws_profile
        else aioboto3.Session()
    )


async def start_build(
    *,
    project: str,
    source_zip_key: str,
    compute_type: str,
    ecr_uri: str,
    image_tag: str,
    timeout_minutes: int | None = None,
) -> str:
    """StartBuild, 返回 build id。timeout_minutes 非空则覆盖 Project 默认超时。"""
    s = get_settings()
    location = f"{s.image_build_source_bucket}/{source_zip_key}"
    kwargs: dict[str, Any] = {
        "projectName": project,
        "sourceLocationOverride": location,
        "computeTypeOverride": compute_type,
        "environmentVariablesOverride": [
            {"name": "ECR_URI", "value": ecr_uri, "type": "PLAINTEXT"},
            {"name": "IMAGE_TAG", "value": image_tag, "type": "PLAINTEXT"},
        ],
    }
    if timeout_minutes is not None:
        kwargs["timeoutInMinutesOverride"] = timeout_minutes
    async with _session().client("codebuild", region_name=s.aws_region) as c:
        resp = await c.start_build(**kwargs)
        return resp["build"]["id"]


async def batch_get_builds(build_ids: list[str]) -> list[dict[str, Any]]:
    """查一批 build 状态; 每项含 id / buildStatus / logs.deepLink / logs.groupName / logs.streamName。"""
    if not build_ids:
        return []
    s = get_settings()
    async with _session().client("codebuild", region_name=s.aws_region) as c:
        resp = await c.batch_get_builds(ids=build_ids)
        return resp.get("builds", [])


async def get_build_log_text(
    build_id: str, *, limit: int = 1000, next_token: str | None = None
) -> tuple[str, str | None]:
    """拉取某 build 的 CloudWatch 日志文本, 支持从头翻页。

    build_id 形如 'image-builder:<uuid>', 日志组 /aws/codebuild/<project>,
    日志流 = <uuid>。返回 (日志文本, next_token)。

    - startFromHead=True 从头取: startFromHead=False (从尾) 首次常返回空 events +
      token (需再翻才有数据), 会误判"暂无日志"。构建日志是整段回看, 从头翻。
    - next_token: 传上次返回的 token 续拉下一页 (前端"加载更多")。
    - 返回的 next_token 为 None 表示已到末尾 (CloudWatch 到底后 forward token 不再
      前进, 即与传入 token 相同; 据此判断无更多)。
    """
    s = get_settings()
    project, _, stream = build_id.partition(":")
    if not stream:
        return "", None
    group = f"/aws/codebuild/{project}"
    kwargs: dict[str, Any] = {
        "logGroupName": group,
        "logStreamName": stream,
        "limit": limit,
    }
    if next_token:
        kwargs["nextToken"] = next_token
    else:
        kwargs["startFromHead"] = True  # 首页从头; 带 token 时方向已由 token 决定
    async with _session().client("logs", region_name=s.aws_region) as c:
        try:
            resp = await c.get_log_events(**kwargs)
        except Exception:  # noqa: BLE001 - 日志还没生成/流不存在/token 失效
            return "", None
        events = resp.get("events", []) or []
        text = "".join(e.get("message", "") for e in events)
        fwd = resp.get("nextForwardToken")
        # 到末尾: forward token 与传入 token 相同 (CloudWatch 语义); 或本页无事件。
        more = fwd is not None and fwd != next_token and len(events) >= limit
        return text, (fwd if more else None)
