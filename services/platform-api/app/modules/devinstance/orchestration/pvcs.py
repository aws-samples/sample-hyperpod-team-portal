"""共享 PVC 列表 (P2) · 创建表单给用户选挂哪块盘."""

from __future__ import annotations

from app.adapters.k8s import K8sAPIError, K8sClient
from app.core.logging import get_logger

from ..api.schemas import SharedPVCInfo
from ..domain.validators import parse_pvc_capacity_gib

logger = get_logger(__name__)


# storage_class 名字推断存储类型 (人性化标签, 前端 UI 用)
_STORAGE_KIND_HINTS: tuple[tuple[str, str], ...] = (
    ("fsx", "FSx Lustre"),
    ("efs", "EFS"),
    ("s3", "S3 Mountpoint"),
    ("ebs", "EBS"),
    ("gp", "EBS"),  # gp2 / gp3
)


def _infer_storage_kind(storage_class: str | None) -> str:
    if not storage_class:
        return "unknown"
    sc = storage_class.lower()
    for hint, label in _STORAGE_KIND_HINTS:
        if hint in sc:
            return label
    return "unknown"


async def list_shared_pvcs(
    k8s: K8sClient, namespace: str
) -> list[SharedPVCInfo]:
    """列 workspace namespace 下 Bound 的 PVC.

    primaryStorage 已是 Workspace operator 自己建的 (name 带 workspace 前缀),
    过滤掉以避免误挂. 其余 PVC 都是管理员手工建的共享盘 (FSx/EFS/S3).
    """
    try:
        items = await k8s.list_pvcs(namespace=namespace, phase_filter="Bound")
    except K8sAPIError as exc:
        logger.info(
            "dev_instance.pvcs.k8s_err",
            ns=namespace,
            code=exc.code,
            msg=exc.message,
        )
        return []
    result: list[SharedPVCInfo] = []
    for p in items:
        meta = p.get("metadata") or {}
        spec = p.get("spec") or {}
        status_ = p.get("status") or {}
        name = meta.get("name", "")
        # 跳过 operator 自建的 primary PVC (名字形如 workspace-<ws>-pvc)
        if name.startswith("workspace-") and name.endswith("-pvc"):
            continue
        sc = spec.get("storageClassName")
        result.append(
            SharedPVCInfo(
                name=name,
                storage_class=sc,
                capacity_gib=parse_pvc_capacity_gib(status_.get("capacity")),
                access_modes=status_.get("accessModes", [])
                or spec.get("accessModes", []),
                phase=status_.get("phase", "Unknown"),
                storage_kind=_infer_storage_kind(sc),
            )
        )
    return result


async def list_permitted_mounts(
    workspace_id: str, username: str
) -> list[SharedPVCInfo]:
    """列该用户在此 ws 被授权的 FSx 挂载 (开发机创建表单用).

    数据源: MountPermissions (GSI username-index). 按 access 返回对应 PVC 名.

    主目录优先: gid == ws.primary_gid 的挂载 (自己 team 的盘) 标 is_primary=True
    并排到列表第一, 供前端优先展示 (其他是 share 来的别 team 盘)。
    """
    from app.modules.workspace import crud as ws_crud
    from app.repositories import mount_permissions as mount_perms_repo

    # 拿 ws 主 gid (1 ws = 1 team = 1 主 gid; 第一次挂 FSx 固化在 metadata)。
    ws = await ws_crud.get_workspace(None, workspace_id)
    ws_md = (ws or {}).get("metadata_json") or {}
    primary_gid_raw = ws_md.get("primary_gid")
    try:
        primary_gid = int(primary_gid_raw) if primary_gid_raw is not None else None
    except (TypeError, ValueError):
        primary_gid = None

    rows = await mount_perms_repo.list_by_user_in_ws(workspace_id, username)
    result: list[SharedPVCInfo] = []
    for r in rows:
        access = r.get("access", "rw")
        pvc = (
            r.get("pvc_name_ro") if access == "ro" else r.get("pvc_name_rw")
        ) or r.get("pvc_name_rw") or ""
        gid = r.get("gid")
        result.append(
            SharedPVCInfo(
                name=pvc,
                storage_class="fsx-sc",
                capacity_gib=None,
                access_modes=["ReadOnlyMany"] if access == "ro" else ["ReadWriteMany"],
                phase="Bound",
                storage_kind="FSx Lustre",
                mount_path=r.get("mount_path"),
                access=access,
                gid=gid,
                is_primary=(primary_gid is not None and gid == primary_gid),
            )
        )
    # 主目录排第一 (stable sort: 主目录提前, 其余保持原相对顺序)
    result.sort(key=lambda p: 0 if p.is_primary else 1)
    return result
