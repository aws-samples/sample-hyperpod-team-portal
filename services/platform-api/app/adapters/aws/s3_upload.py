"""S3 上传 (aioboto3) · 镜像构建 context zip。"""

from __future__ import annotations

import aioboto3

from app.core.config import get_settings


def _session() -> aioboto3.Session:
    s = get_settings()
    return (
        aioboto3.Session(profile_name=s.aws_profile)
        if s.aws_profile
        else aioboto3.Session()
    )


async def put_bytes(bucket: str, key: str, data: bytes) -> None:
    s = get_settings()
    async with _session().client("s3", region_name=s.aws_region) as c:
        await c.put_object(Bucket=bucket, Key=key, Body=data)
