"""DevInstance DTO 构建.

PR feat/no-users-table-username-as-id, 2026-05-20:
    - 不再调 user_crud.get_user 反查 (Users 表删了)
    - creator_display_name 直接读 row 的冗余字段
"""

from __future__ import annotations

from typing import Any

from app.core.i18n import t

from ..api.schemas import (
    AccessInfo,
    DevInstanceDetail,
    DevInstanceListItem,
)


async def build_list_item(
    db: Any,
    row: dict[str, Any],
) -> DevInstanceListItem:
    """不查 workspace: 列表/详情前端都不用 workspace_display_name, 省每行 (及整页那次预查) GetItem。"""
    del db
    return DevInstanceListItem(
        id=str(row.get("id") or ""),
        workspace_id=str(row.get("workspace_id") or ""),
        creator_user_id=str(row.get("creator_user_id") or ""),
        creator_display_name=row.get("creator_display_name") or row.get("creator_user_id") or "",
        name=row.get("name") or "",
        display_name=row.get("display_name") or "",
        k8s_workspace_name=row.get("k8s_workspace_name") or "",
        template_name=row.get("template_name") or "",
        app_type=row.get("app_type") or "",
        phase=row.get("phase") or "Creating",
        kueue_status=row.get("kueue_status"),
        cpu_request_millicores=int(row.get("cpu_request_millicores") or 0),
        memory_request_mib=int(row.get("memory_request_mib") or 0),
        gpu_count=int(row.get("gpu_count") or 0),
        efa_count=int(row.get("efa_count") or 0),
        storage_size_gib=int(row.get("storage_size_gib") or 0),
        access_url=row.get("access_url"),
        created_at=row.get("created_at") or "",
        started_at=row.get("started_at"),
        last_sync_at=row.get("last_sync_at"),
    )


async def build_detail(
    db: Any,
    row: dict[str, Any],
    conditions: list[dict[str, Any]] | None = None,
) -> DevInstanceDetail:
    del db
    base = await build_list_item(None, row)
    vm_raw = (row.get("metadata_json") or {}).get("volume_mounts") or []
    volume_mounts: list[dict[str, Any]] = []
    for v in vm_raw:
        if all(k in v for k in ("name", "mount_path", "pvc_name")):
            volume_mounts.append(v)
    return DevInstanceDetail(
        **base.model_dump(),
        description=row.get("description"),
        instance_type=(row.get("metadata_json") or {}).get("instance_type"),
        pool=(row.get("metadata_json") or {}).get("pool"),
        k8s_namespace=row.get("k8s_namespace") or "",
        image=row.get("image") or "",
        desired_status=row.get("desired_status") or "Running",
        priority_class=row.get("priority_class"),
        ssm_managed_id=row.get("ssm_managed_id"),
        ssm_init_status=row.get("ssm_init_status") or "pending",
        last_condition_message=row.get("last_condition_message"),
        env=row.get("env_json") or {},
        volume_mounts=volume_mounts,
        conditions=conditions or [],
    )


_SSH_PORT = 22222
_SSH_USER = "sagemaker-user"


async def build_access_info(
    instance: dict[str, Any], k8s: Any = None
) -> AccessInfo:
    """directSSH 接入信息.

    连接靠固定 DNS 名 (VPC 内私有 zone, 停启不变) + sshd :22222。DNS 名从开发机
    对应的 ssh-<name> Service 的 external-dns 注解读回 (k8s 传入时)。鉴权走公钥:
    用户在 code editor 里把自己的公钥贴进 pod 的 ~/.ssh/authorized_keys。
    """
    notes: list[str] = []
    ssh_command: str | None = None
    ssh_config_snippet: str | None = None
    hostname: str | None = None

    phase = instance.get("phase") or "Creating"

    namespace = instance.get("k8s_namespace")
    workspace_name = instance.get("k8s_workspace_name")
    if k8s is not None and namespace and workspace_name:
        try:
            hostname = await k8s.get_ssh_service_hostname(
                namespace, workspace_name
            )
        except Exception:  # noqa: BLE001
            hostname = None

    if hostname:
        # 一行 ssh: 复制即连 (无 ProxyCommand, 固定 DNS 直连内网 sshd)。
        ssh_command = (
            f"ssh {_SSH_USER}@{hostname} -p {_SSH_PORT}"
        )
        # VSCode Remote-SSH 用: HostName 是固定 DNS, 停启不变, 无需 ProxyCommand。
        host_alias = instance.get("name") or hostname
        ssh_config_snippet = (
            f"Host {host_alias}\n"
            f"  HostName {hostname}\n"
            f"  User {_SSH_USER}\n"
            f"  Port {_SSH_PORT}"
        )
        notes.append(t("devinstance.access_note_first_connect"))
    elif "Available" in phase:
        notes.append(t("devinstance.access_note_dns_syncing"))
    else:
        notes.append(t("devinstance.access_note_not_running", phase=phase))

    notes.append(t("devinstance.access_note_ebs"))

    return AccessInfo(
        id=str(instance.get("id") or ""),
        phase=phase,
        ssh_hostname=hostname,
        ssh_port=_SSH_PORT,
        ssh_user=_SSH_USER,
        ssh_command=ssh_command,
        ssh_config_snippet=ssh_config_snippet,
        notes=notes,
    )
