"""S3 buckets 异步操作 (aioboto3).

职责:
    - 列 admin 预建打 managed=hyperpod tag 的 bucket (workspace S3 挂载用)
    - 校验单个 bucket 存在 + 拿 region
    - 上传文本对象 (put_text)

Workspace S3 挂载走 list_managed_buckets / verify_bucket.
(账号级 list_buckets / list_objects 已删, 见下方 NOTE。)
"""

from __future__ import annotations

from typing import Any

import aioboto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class S3APIError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def _tags_to_dict(tag_set: list[dict[str, str]] | None) -> dict[str, str]:
    return {t["Key"]: t["Value"] for t in (tag_set or [])}


# NOTE: list_buckets / list_objects (账号级 S3 列举) 已删 (2026-06-14):
# 唯一调用方是 registry 模块的 S3 dropdown 端点, 那两个端点无 ws 隔离 + 前端无人调用,
# 已一并删除。Workspace S3 挂载走下面的 list_managed_buckets / verify_bucket。


# ============================================================
# Workspace S3 挂载相关 (Mountpoint S3 CSI Driver)
# ============================================================

def _parse_platform_s3_buckets(raw: str, default_region: str) -> list[dict[str, Any]]:
    """解析 PLATFORM_S3_BUCKETS 环境变量.

    格式: bucket[:region[:friendly_name]],bucket2[:region2[:friendly_name2]]
    region / friendly_name 都可选; 缺 region 用 default_region, 缺 name 用 bucket.
    """
    out: list[dict[str, Any]] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":", 2)
        bucket = parts[0].strip()
        if not bucket:
            continue
        region = (parts[1].strip() if len(parts) > 1 else "") or default_region
        name = (parts[2].strip() if len(parts) > 2 else "") or bucket
        out.append(
            {
                "bucket_name": bucket,
                "name": name,
                "region": region,
                "tags": {},  # 跳过 tag 路径, 没 tag 数据
            }
        )
    return out


async def list_managed_buckets() -> list[dict[str, Any]]:
    """列候选池. 给 admin 加 S3 挂载时下拉用.

    两种模式:
      - PLATFORM_S3_BUCKETS 设置: 直接读环境变量列出的 bucket (0 次 AWS 调用,
        替代账号下 list_buckets + N 次 get_bucket_tagging 的慢链, 26s → ~50ms)
      - 否则: list_buckets 全账号 + 每个 bucket 调 get_bucket_tagging 过滤
        Tags[managed]=hyperpod (账号 bucket 多时极慢)

    Returns:
        [{"bucket_name", "name", "region", "tags"}, ...]
    """
    s = get_settings()

    # 快路径: 直接读环境变量, 跳过 AWS
    if s.platform_s3_buckets:
        out = _parse_platform_s3_buckets(s.platform_s3_buckets, s.aws_region)
        logger.info("s3.list_managed.from_env", eligible=len(out))
        return out

    # 慢路径 (兜底): 走 tag 过滤
    session = aioboto3.Session(
        profile_name=s.aws_profile or None, region_name=s.aws_region
    )

    try:
        async with session.client("s3", region_name=s.aws_region) as client:
            list_resp = await client.list_buckets()
    except ClientError as exc:
        err = exc.response.get("Error", {})
        raise S3APIError(
            err.get("Code", "Unknown"), err.get("Message", str(exc))
        ) from exc
    except BotoCoreError as exc:
        raise S3APIError("BotoCoreError", str(exc)) from exc

    out: list[dict[str, Any]] = []
    async with session.client("s3", region_name=s.aws_region) as client:
        for b in list_resp.get("Buckets") or []:
            bucket = b.get("Name")
            if not bucket:
                continue
            # 拉 tags (失败/无 tag 跳过)
            try:
                tags_resp = await client.get_bucket_tagging(Bucket=bucket)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code != "NoSuchTagSet":
                    logger.info(
                        "s3.list.tags_skip", bucket=bucket, code=code
                    )
                continue
            tags = _tags_to_dict(tags_resp.get("TagSet"))
            if tags.get("managed") != "hyperpod":
                continue

            # 拿 region (us-east-1 返 None, 用 fallback)
            try:
                loc_resp = await client.get_bucket_location(Bucket=bucket)
                region = loc_resp.get("LocationConstraint") or "us-east-1"
            except ClientError:
                region = s.aws_region

            out.append(
                {
                    "bucket_name": bucket,
                    "name": tags.get("Name") or bucket,
                    "region": region,
                    "tags": tags,
                }
            )

    logger.info("s3.list_managed.ok", eligible=len(out))
    return out


async def put_text(
    *,
    bucket: str,
    key: str,
    body: str,
    region: str | None = None,
    content_type: str = "text/yaml",
) -> str:
    """上传文本对象到 S3, 返回 s3:// URI.

    复用既有 Session 构造 (profile + region). region 缺省用 settings.aws_region;
    传 bucket 所在 region 避免 PermanentRedirect.
    """
    s = get_settings()
    target_region = region or s.aws_region
    session = aioboto3.Session(
        profile_name=s.aws_profile or None, region_name=target_region
    )
    try:
        async with session.client("s3", region_name=target_region) as client:
            await client.put_object(
                Bucket=bucket,
                Key=key,
                Body=body.encode("utf-8"),
                ContentType=content_type,
            )
    except ClientError as exc:
        err = exc.response.get("Error", {})
        raise S3APIError(
            err.get("Code", "Unknown"), err.get("Message", str(exc))
        ) from exc
    except BotoCoreError as exc:
        raise S3APIError("BotoCoreError", str(exc)) from exc

    return f"s3://{bucket}/{key}"


async def verify_bucket(bucket_name: str) -> dict[str, Any]:
    """校验 bucket 存在 + 拿 region. 用于 attach 流校验.

    不强求 managed=hyperpod tag (admin 可绕过 UI 直接挂任何 bucket).
    """
    s = get_settings()
    session = aioboto3.Session(
        profile_name=s.aws_profile or None, region_name=s.aws_region
    )
    try:
        async with session.client("s3", region_name=s.aws_region) as client:
            await client.head_bucket(Bucket=bucket_name)
            loc_resp = await client.get_bucket_location(Bucket=bucket_name)
    except ClientError as exc:
        err = exc.response.get("Error", {})
        code = err.get("Code", "Unknown")
        if code in ("404", "NoSuchBucket", "NoSuchBucketException"):
            raise S3APIError(
                "NotFound", f"S3 bucket {bucket_name} not found"
            ) from exc
        raise S3APIError(code, err.get("Message", str(exc))) from exc
    except BotoCoreError as exc:
        raise S3APIError("BotoCoreError", str(exc)) from exc

    region = loc_resp.get("LocationConstraint") or "us-east-1"
    return {
        "bucket_name": bucket_name,
        "region": region,
    }
