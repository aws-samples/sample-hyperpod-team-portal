"""AWS FSx Lustre adapter — 列候选池 + 拿单个 FSx 元数据.

职责:
    - list_managed_filesystems: 列 admin 预建的可挂载 FSx (过滤 managed=hyperpod + AVAILABLE)
    - describe_filesystem: 拿单个 FSx 的 DNSName / MountName / Tags / SubnetIds
                          (PV 字段需要)

设计:
    - 不缓存 (admin 加 / 删 FSx 频率低, 但加后立即列出符合直觉)
    - 不返回 CSI 动态建的 FSx (按文档 §1.2 规则: 不打 managed=hyperpod 的不在候选)
"""

from __future__ import annotations

import re
from typing import Any

import aioboto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings
from app.core.i18n import t
from app.core.logging import get_logger

logger = get_logger(__name__)

# fs-id 天然路径安全 (fs-<hex>): 小写字母数字 + 连字符, 直接当 fsx-admin 挂载点
# 子目录 /fsx-mnt/<fs-id>, 无需再引入人工别名。
_FSX_ID_RE = re.compile(r"^fs-[0-9a-f]+$")


class FsxAPIError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def _parse_platform_fsx(raw: str) -> list[str]:
    """解析 PLATFORM_FSX_FILESYSTEMS = 'fs-id,fs-id2,...' → [fs_id, ...].

    fs-id 直接当挂载点子目录 (天然路径安全), 无人工别名。展示名走 AWS Tags[Name]。
    兼容旧格式 'fs-id:别名' —— 取冒号前的 fs-id, 忽略别名段 (老 cdk.json 不改也能跑)。
    非法 fs-id / 重复 → 抛 ValueError (部署即失败)。
    """
    out: list[str] = []
    seen: set[str] = set()
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        # 旧格式 fs-id:别名 → 只取 fs-id (别名段已废弃)。
        fs_id = entry.split(":", 1)[0].strip()
        if not _FSX_ID_RE.match(fs_id):
            raise ValueError(t("aws.fsx_id_invalid", fs_id=repr(fs_id)))
        if fs_id in seen:
            raise ValueError(t("aws.fsx_id_duplicate", fs_id=repr(fs_id)))
        seen.add(fs_id)
        out.append(fs_id)
    return out


def configured_fsx_filesystems() -> list[str]:
    """cdk.json/env 配的 FSx id 列表 (不查 AWS)。留空 = 未配。"""
    return _parse_platform_fsx(get_settings().platform_fsx_filesystems or "")


def is_configured_filesystem(filesystem_id: str) -> bool:
    """该 fs 是否在 PLATFORM_FSX_FILESYSTEMS 配了 (决定能否做配额/挂载点)。"""
    return filesystem_id in configured_fsx_filesystems()


def _tags_to_dict(tags_list: list[dict[str, str]] | None) -> dict[str, str]:
    return {t["Key"]: t["Value"] for t in (tags_list or [])}


def _normalize(fs: dict[str, Any]) -> dict[str, Any]:
    """boto3 PascalCase response → 业务侧扁平 dict.

    返回:
        filesystem_id, dns_name, mount_name, capacity_gib, lifecycle,
        deployment_type, subnet_id, vpc_id, kms_key_id, tags{}, name(tag)
    """
    lustre = fs.get("LustreConfiguration") or {}
    tags = _tags_to_dict(fs.get("Tags"))
    return {
        "filesystem_id": fs.get("FileSystemId"),
        "dns_name": fs.get("DNSName"),
        "mount_name": lustre.get("MountName"),
        "capacity_gib": fs.get("StorageCapacity"),
        "lifecycle": fs.get("Lifecycle"),
        "deployment_type": lustre.get("DeploymentType"),
        "per_unit_storage_throughput": lustre.get("PerUnitStorageThroughput"),
        "subnet_id": (fs.get("SubnetIds") or [None])[0],
        "vpc_id": fs.get("VpcId"),
        "kms_key_id": fs.get("KmsKeyId"),
        "tags": tags,
        "name": tags.get("Name") or fs.get("FileSystemId"),
    }


def _is_eligible(fs_normalized: dict[str, Any]) -> bool:
    """文档 §1.2 过滤规则: managed=hyperpod + AVAILABLE."""
    if fs_normalized.get("tags", {}).get("managed") != "hyperpod":
        return False
    if fs_normalized.get("lifecycle") != "AVAILABLE":
        return False
    return True


async def list_managed_filesystems() -> list[dict[str, Any]]:
    """列候选池. 给 admin 创建 ws / 加 FSx 挂载 / 配额/监控下拉用.

    两种模式:
      - PLATFORM_FSX_FILESYSTEMS 设置: 按配的 fs-id 列表逐个 describe。展示名 (name)
        取 AWS Tags[Name] (拿不到则 fs-id)。不可达的 fs 跳过并告警, 不整体失败。
      - 否则 (留空): Tags[managed]=hyperpod 且 Lifecycle=AVAILABLE。
    """
    s = get_settings()

    # 多 FSx 模式: 按配的 fs-id 列表逐个 describe (name 来自 _normalize 的 Tags[Name])
    configured = configured_fsx_filesystems()
    if configured:
        out: list[dict[str, Any]] = []
        for fs_id in configured:
            try:
                fs = await describe_filesystem(fs_id)
            except FsxAPIError:
                logger.warning("fsx.list.configured_unreachable", fs_id=fs_id)
                continue
            out.append(fs)
        logger.info("fsx.list.configured", total=len(configured), ok=len(out))
        return out

    session = aioboto3.Session(
        profile_name=s.aws_profile or None, region_name=s.aws_region
    )
    try:
        async with session.client("fsx", region_name=s.aws_region) as client:
            resp = await client.describe_file_systems()
    except ClientError as exc:
        err = exc.response.get("Error", {})
        raise FsxAPIError(
            err.get("Code", "Unknown"), err.get("Message", str(exc))
        ) from exc
    except BotoCoreError as exc:
        raise FsxAPIError("BotoCoreError", str(exc)) from exc

    out: list[dict[str, Any]] = []
    for fs in resp.get("FileSystems") or []:
        if fs.get("FileSystemType") != "LUSTRE":
            continue
        nfs = _normalize(fs)
        if _is_eligible(nfs):
            # 此 fallback 路径的 fs 未配进 PLATFORM_FSX_FILESYSTEMS, 只用于展示;
            # 配额/挂载点仍要求显式配置 (拼不出挂载根)。name 来自 Tags[Name]。
            out.append(nfs)
    logger.info("fsx.list.ok", total=len(resp.get("FileSystems") or []), eligible=len(out))
    return out


async def describe_filesystem(filesystem_id: str) -> dict[str, Any]:
    """拿单个 FSx 详情 (创建 PV 时取 DNS+MountName 用).

    不做 managed= 过滤 — 调这条的前提是上层已经知道 fs_id 有效.
    但仍校验 LUSTRE + AVAILABLE.
    """
    s = get_settings()
    session = aioboto3.Session(
        profile_name=s.aws_profile or None, region_name=s.aws_region
    )
    try:
        async with session.client("fsx", region_name=s.aws_region) as client:
            resp = await client.describe_file_systems(FileSystemIds=[filesystem_id])
    except ClientError as exc:
        err = exc.response.get("Error", {})
        raise FsxAPIError(
            err.get("Code", "Unknown"), err.get("Message", str(exc))
        ) from exc
    except BotoCoreError as exc:
        raise FsxAPIError("BotoCoreError", str(exc)) from exc

    items = resp.get("FileSystems") or []
    if not items:
        raise FsxAPIError("NotFound", f"FSx {filesystem_id} not found")
    fs = items[0]
    if fs.get("FileSystemType") != "LUSTRE":
        raise FsxAPIError(
            "InvalidType",
            f"FSx {filesystem_id} is {fs.get('FileSystemType')}, only LUSTRE supported",
        )
    nfs = _normalize(fs)
    if nfs.get("lifecycle") != "AVAILABLE":
        raise FsxAPIError(
            "NotAvailable",
            f"FSx {filesystem_id} lifecycle is {nfs.get('lifecycle')}, must be AVAILABLE",
        )
    return nfs
