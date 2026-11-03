"""ECR 仓库 / 镜像 tag 异步列举 (aioboto3).

职责:
    - 列 ECR 仓库 (DescribeRepositories)
    - 列指定仓库镜像 tag (DescribeImages)

业务侧 (app/modules/registry) 只负责 schema + auth 包装.
"""

from __future__ import annotations

import json
from typing import Any

import aioboto3

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def list_repositories(*, max_results: int = 100) -> list[dict[str, Any]]:
    """列 ECR 仓库.

    Returns:
        [{"name", "uri", "registry_id"}], 顺序由 ECR 返回, 上层可二次排序.
    """
    settings = get_settings()
    session = aioboto3.Session(region_name=settings.aws_region)
    out: list[dict[str, Any]] = []
    async with session.client("ecr") as client:
        paginator = client.get_paginator("describe_repositories")
        async for page in paginator.paginate(
            PaginationConfig={"PageSize": min(max_results, 100)}
        ):
            for r in page.get("repositories", []):
                out.append(
                    {
                        "name": r.get("repositoryName"),
                        "uri": r.get("repositoryUri"),
                        "registry_id": r.get("registryId"),
                    }
                )
                if len(out) >= max_results:
                    return out
    return out


async def list_image_tags(
    repository_name: str, *, max_results: int = 50
) -> list[dict[str, Any]]:
    """列指定 ECR 仓库 image tag.

    Returns:
        [{"tag", "digest", "pushed_at_iso", "size_mb"}], 按 imagePushedAt 倒序.
        过滤掉无 tag 的 manifest (untagged build artifact).
    """
    settings = get_settings()
    session = aioboto3.Session(region_name=settings.aws_region)
    out: list[dict[str, Any]] = []
    async with session.client("ecr") as client:
        paginator = client.get_paginator("describe_images")
        async for page in paginator.paginate(
            repositoryName=repository_name,
            filter={"tagStatus": "TAGGED"},
            PaginationConfig={"PageSize": min(max_results, 100)},
        ):
            for img in page.get("imageDetails", []):
                pushed = img.get("imagePushedAt")
                size_bytes = img.get("imageSizeInBytes") or 0
                for tag in img.get("imageTags") or []:
                    out.append(
                        {
                            "tag": tag,
                            "digest": img.get("imageDigest"),
                            "pushed_at_iso": pushed.isoformat() if pushed else None,
                            "size_mb": round(size_bytes / 1024 / 1024, 1),
                        }
                    )
            if len(out) >= max_results:
                break
    out.sort(key=lambda x: x.get("pushed_at_iso") or "", reverse=True)
    return out[:max_results]


async def ensure_repository(repo_name: str, *, keep_last: int = 10) -> str:
    """幂等建 ECR repo + lifecycle policy (留最近 keep_last 个 tag), 返 repositoryUri。

    已存在 → 直接返回其 uri; 不存在 → 建 + 挂 lifecycle。写操作用带 profile 的
    session (本地 demo 靠 aws_profile, 与 ssm adapter 同源)。
    """
    settings = get_settings()
    session = (
        aioboto3.Session(profile_name=settings.aws_profile)
        if settings.aws_profile
        else aioboto3.Session()
    )
    async with session.client("ecr", region_name=settings.aws_region) as client:
        try:
            resp = await client.describe_repositories(repositoryNames=[repo_name])
            return resp["repositories"][0]["repositoryUri"]
        except client.exceptions.RepositoryNotFoundException:
            pass
        resp = await client.create_repository(repositoryName=repo_name)
        uri = resp["repository"]["repositoryUri"]
        policy = {
            "rules": [
                {
                    "rulePriority": 1,
                    "description": f"keep last {keep_last} images",
                    "selection": {
                        "tagStatus": "any",
                        "countType": "imageCountMoreThan",
                        "countNumber": keep_last,
                    },
                    "action": {"type": "expire"},
                }
            ]
        }
        await client.put_lifecycle_policy(
            repositoryName=repo_name, lifecyclePolicyText=json.dumps(policy)
        )
        return uri
