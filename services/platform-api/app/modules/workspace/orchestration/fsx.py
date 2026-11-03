"""Workspace FSx 挂载 / 卸载 orchestration.

attach_fsx_flow:
    1. 校验 ws 存在
    2. 校验 fs_id 有效 (走 AWS DescribeFileSystem 拿 DNS+MountName)
    3. 校验 mount_path 不与已挂载冲突
    4. 校验 fs_id 没重复挂 (DDB metadata.fsx_mounts)
    5. 建 K8s PV (claimRef 锁 ns/pvc)
    6. 建 K8s PVC (volumeName 双向绑)
    7. 改 DDB metadata.fsx_mounts append 一项
    8. AuditLog

detach_fsx_flow:
    1. 校验 ws 存在 + fs_id 在挂载列表
    2. (force=False) 检查 pod 占用 → 占用则 409
    3. 删 PVC + 删 PV
    4. 改 DDB metadata.fsx_mounts 移除该项
    5. AuditLog

list_workspace_fsx_flow:
    读 DDB metadata.fsx_mounts + 实时调 fsx:DescribeFileSystem 拿当前元数据.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

from app.adapters.aws import fsx as fsx_adapter
from app.adapters.aws.fsx import FsxAPIError
from app.adapters.ddb import tables as ddb_tables
from app.adapters.k8s import K8sAPIError, K8sClient
from app.adapters.k8s.workspace_resources import fsx_pv_name as fsx_pv_name_of
from app.adapters.k8s.workspace_resources import fsx_pvc_name as fsx_pvc_name_of
from app.core.i18n import t
from app.core.logging import get_logger
from app.modules.workspace.persistence import crud
from app.repositories import audit_log as audit_repo
from app.repositories import mount_permissions as mount_perms_repo
from app.repositories import workspaces as ws_repo

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _get_ws_or_404(ws_id: str) -> dict[str, Any]:
    ws = await crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"workspace not found: {ws_id}",
        )
    return ws


async def list_workspace_fsx_flow(ws_id: str) -> list[dict[str, Any]]:
    """列已挂 FSx + 实时拉 FSx 元数据 (用于前端展示 size/dns)."""
    ws = await _get_ws_or_404(ws_id)
    metadata = ws.get("metadata_json") or {}
    mounts = list(metadata.get("fsx_mounts") or [])

    # 实时拉每个 fs 的元数据 (失败不阻断, 字段返 None)
    enriched: list[dict[str, Any]] = []
    for m in mounts:
        fs_id = m.get("filesystem_id")
        item: dict[str, Any] = {
            "filesystem_id": fs_id,
            "mount_id": m.get("mount_id") or "",
            "description": m.get("description") or "",
            "mount_path": m.get("mount_path"),
            "pv_name": m.get("pv_name"),
            "pvc_name": m.get("pvc_name"),
            "pvc_name_rw": m.get("pvc_name_rw"),
            "pvc_name_ro": m.get("pvc_name_ro"),
            "attached_at": m.get("attached_at") or "",
            "subdir": m.get("subdir"),
            "gid": m.get("gid"),
            "name": None,
            "capacity_gib": None,
            "dns_name": None,
            # mount_name: FSx 原始 lustre mountname (describe 实时拿).
            # full_mount_name: mount_name 拼 subdir (= operator/PV 用的挂载名, 锁 team 层).
            # 推理模型源用 full_mount_name 当 fsxStorage.mountName 实现子目录隔离.
            "mount_name": None,
            "full_mount_name": None,
        }
        if fs_id:
            try:
                fs = await fsx_adapter.describe_filesystem(fs_id)
                item["name"] = fs.get("name")
                item["capacity_gib"] = fs.get("capacity_gib")
                item["dns_name"] = fs.get("dns_name")
                mn = fs.get("mount_name")
                item["mount_name"] = mn
                subdir = m.get("subdir")
                item["full_mount_name"] = (
                    f"{mn}/{subdir}" if mn and subdir else mn
                )
            except FsxAPIError as exc:
                logger.warning(
                    "workspace.fsx.describe_fail",
                    ws_id=ws_id,
                    fs_id=fs_id,
                    err=str(exc),
                )
        enriched.append(item)
    return enriched


def _assert_fsx_attach_allowed(
    actor: dict[str, Any], primary_gid: int | None, probed_gid: int
) -> None:
    """非平台超管时: ws 未固化 primary_gid 则禁首挂; 否则探测 gid 必须 == primary_gid。

    平台超管不受限(可挂首个、可挂任意 gid)。
    """
    if actor.get("is_admin") is True:
        return
    if primary_gid is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t("workspace.fsx_first_mount_admin_only"),
        )
    if int(probed_gid) != int(primary_gid):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t("workspace.fsx_gid_mismatch", primary_gid=primary_gid, probed_gid=probed_gid),
        )


async def attach_fsx_flow(
    *,
    ws_id: str,
    filesystem_id: str,
    mount_path: str,
    subdir: str,
    mount_id: str,
    description: str,
    current_user: dict[str, Any],
    k8s: K8sClient,
) -> list[dict[str, Any]]:
    """挂载 FSx 到 ws.

    gid 由后端探测目录真实值 (子目录 gid 可能 ≠ 父目录). ws 第一次挂载时把
    探测到的 gid 固化为 metadata.primary_gid (1 ws = 1 team = 1 主 gid).
    每条挂载双建 rw-PV + ro-PV (ro 靠 mountOptions:[ro], 设计 §2.3).
    """
    ws = await _get_ws_or_404(ws_id)
    metadata = ws.get("metadata_json") or {}
    namespace = metadata.get("namespace") or ws.get("namespace")
    workspace_name = metadata.get("name") or ws.get("display_name") or ""

    if not namespace:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="workspace has no namespace (data inconsistency)",
        )

    existing_mounts: list[dict[str, Any]] = list(metadata.get("fsx_mounts") or [])

    # mount_id 在 FSx 维度 ws 内唯一 (PVC 名直接用 mount_id, K8s 不允许同 ns 重名)
    for m in existing_mounts:
        if m.get("mount_id") == mount_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"FSx mount_id '{mount_id}' already exists in workspace",
            )

    # 同 (fs, subdir) 不能重挂. 用户场景: 集群只一块 FSx, 一个 ws 挂多个子目录
    # (data + checkpoint 等), 用 mount_id 区分.
    for m in existing_mounts:
        if (
            m.get("filesystem_id") == filesystem_id
            and m.get("subdir") == subdir
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"FSx {filesystem_id} subdir '{subdir}' already attached"
                ),
            )

    # 检查 mount_path 不与已挂冲突 (跨 FSx + S3 同 ws 内)
    for m in existing_mounts:
        if m.get("mount_path") == mount_path:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"mount_path {mount_path} already used by FSx {m.get('filesystem_id')}",
            )

    # 跨 team 共享: 一个 ws 可挂多个不同 gid 的目录 (自己 team + share 来的别 team).
    # 不再强制"同 ws 单 gid" (设计 §2.1).

    # 拿 FSx 元数据 (这一步同时校验 fs 存在 + AVAILABLE + LUSTRE)
    try:
        fs_info = await fsx_adapter.describe_filesystem(filesystem_id)
    except FsxAPIError as exc:
        if exc.code == "NotFound":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    dns_name = fs_info["dns_name"]
    mount_name = fs_info["mount_name"]
    capacity_gib = fs_info["capacity_gib"] or 1200

    # 探测目录真实 gid (子目录 gid 可能 ≠ 父目录, 必须探测真值, 设计 §5.1).
    # 多 FSx: fsx-admin pod 里该盘挂在 /fsx-mnt/<fs-id> 下。
    probe_path = f"{_fsx_admin_root(filesystem_id)}/{subdir}"
    gid = await probe_dir_gid(probe_path)
    if gid is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("workspace.fsx_probe_failed", path=probe_path),
        )

    # 非平台超管: 校验 gid 约束 (首挂禁止 + 只能挂 primary_gid 目录, 设计 §2.2)
    _assert_fsx_attach_allowed(
        current_user, metadata.get("primary_gid"), gid
    )

    # 双建 rw-PV + ro-PV + 对应 PVC (ro 靠 mountOptions:[ro]).
    created_pvs: list[str] = []
    created_pvcs: list[tuple[str, str]] = []  # (namespace, pvc_name)
    pvc_name_rw: str | None = None
    pvc_name_ro: str | None = None
    try:
        for access in ("rw", "ro"):
            pv_name = await k8s.create_fsx_pv(
                workspace_id=str(ws_id),
                workspace_name=workspace_name,
                namespace=namespace,
                filesystem_id=filesystem_id,
                dns_name=dns_name,
                mount_name=mount_name,
                capacity_gib=capacity_gib,
                mount_id=mount_id,
                subdir=subdir,
                access=access,
            )
            created_pvs.append(pv_name)
            pvc_name = await k8s.create_fsx_pvc(
                namespace=namespace,
                workspace_name=workspace_name,
                filesystem_id=filesystem_id,
                pv_full_name=pv_name,
                capacity_gib=capacity_gib,
                mount_id=mount_id,
                access=access,
            )
            created_pvcs.append((namespace, pvc_name))
            if access == "rw":
                pvc_name_rw = pvc_name
            else:
                pvc_name_ro = pvc_name
    except K8sAPIError as exc:
        # 反向回滚已建的 PVC + PV
        for ns_, pvc_ in created_pvcs:
            try:
                await k8s.delete_pvc(ns_, pvc_)
            except Exception:
                pass
        for pv_ in created_pvs:
            try:
                await k8s.delete_pv(pv_)
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"K8s create PV/PVC failed [{exc.code}]: {exc.message}",
        ) from exc

    # 回读校验 (verify-after-write): 确认 rw + ro 两个 PVC 都真的建出来了,
    # 再写 DDB. 防 DDB 记了"两套都有"但 K8s 实际只半套 (create 静默
    # already_exists / 残留 等) 的 drift. 校验失败 → 回滚 + 报错, DDB 不落库.
    verify_failed: list[str] = []
    for pvc_check in (pvc_name_rw, pvc_name_ro):
        try:
            if not await k8s.pvc_exists(namespace, pvc_check):
                verify_failed.append(pvc_check)
        except K8sAPIError:
            verify_failed.append(pvc_check)
    if verify_failed:
        # 回滚已建的 (best-effort), DDB 不落库
        for ns_, pvc_ in created_pvcs:
            try:
                await k8s.delete_pvc(ns_, pvc_)
            except Exception:
                pass
        for pv_ in created_pvs:
            try:
                await k8s.delete_pv(pv_)
            except Exception:
                pass
        logger.warning(
            "workspace.fsx.attach.verify_failed",
            ws_id=ws_id, mount_id=mount_id, missing=verify_failed,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                t("workspace.fsx_verify_failed", missing=verify_failed)
            ),
        )

    # 改 DDB metadata.fsx_mounts + 第一次挂载固化 primary_gid
    new_mount = {
        "mount_id": mount_id,
        "description": description,
        "filesystem_id": filesystem_id,
        "mount_path": mount_path,
        "pv_name": created_pvs[0],          # rw-PV (兼容旧字段)
        "pvc_name": pvc_name_rw,            # 兼容旧字段 = rw PVC
        "pvc_name_rw": pvc_name_rw,
        "pvc_name_ro": pvc_name_ro,
        "attached_at": _now_iso(),
        "subdir": subdir,
        "gid": gid,
    }
    new_mounts = existing_mounts + [new_mount]
    new_metadata = dict(metadata)
    new_metadata["fsx_mounts"] = new_mounts
    # 第一次挂载固化 primary_gid (1 ws = 1 team = 1 主 gid, 设计 §2.1).
    # 第一次挂载按约定是自己 team 目录, 不另做判断.
    if new_metadata.get("primary_gid") is None:
        new_metadata["primary_gid"] = gid
    try:
        await ws_repo.update_workspace(ws_id, metadata=new_metadata)
    except Exception as exc:
        # DDB 失败回滚 K8s (删两套 PV/PVC)
        for ns_, pvc_ in created_pvcs:
            try:
                await k8s.delete_pvc(ns_, pvc_)
            except Exception:
                pass
        for pv_ in created_pvs:
            try:
                await k8s.delete_pv(pv_)
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DDB update failed (K8s rolled back): {exc}",
        ) from exc

    # AuditLog
    actor = current_user
    actor_username = str(actor.get("username") or actor.get("user_id") or "")
    try:
        await audit_repo.append(
            scope_key=ddb_tables.scope_key_workspace(str(ws_id)),
            actor_user_id=actor_username,
            actor_role="platform-admin",
            operation="workspace.fsx.attach",
            target_type="workspace",
            target_id=str(ws_id),
            status="succeeded",
            metadata={
                "mount_id": mount_id,
                "filesystem_id": filesystem_id,
                "mount_path": mount_path,
                "pvc_name_rw": pvc_name_rw,
                "pvc_name_ro": pvc_name_ro,
                "subdir": subdir,
                "gid": gid,
                "actor_email": actor.get("email") or "",
            },
        )
    except Exception as audit_exc:  # pragma: no cover
        logger.warning(
            "workspace.fsx.attach.audit_fail", ws_id=ws_id, err=str(audit_exc)
        )

    logger.info(
        "workspace.fsx.attach.ok",
        ws_id=ws_id,
        fs_id=filesystem_id,
        mount_path=mount_path,
    )
    return await list_workspace_fsx_flow(ws_id)


async def detach_fsx_flow(
    *,
    ws_id: str,
    mount_id: str,
    force: bool,
    current_user: dict[str, Any],
    k8s: K8sClient,
) -> list[dict[str, Any]]:
    """卸载 FSx (按 mount_id)."""
    ws = await _get_ws_or_404(ws_id)
    metadata = ws.get("metadata_json") or {}
    namespace = metadata.get("namespace") or ws.get("namespace")
    existing_mounts: list[dict[str, Any]] = list(metadata.get("fsx_mounts") or [])

    target = None
    target_idx = -1
    for i, m in enumerate(existing_mounts):
        if m.get("mount_id") == mount_id:
            target = m
            target_idx = i
            break
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"FSx mount_id '{mount_id}' not attached to workspace {ws_id}",
        )

    filesystem_id = target.get("filesystem_id") or ""
    # rw + ro 两套 PV/PVC (新规则双建). 优先用 DDB 字面值, fallback 按命名规则推.
    pvc_rw = target.get("pvc_name_rw") or target.get("pvc_name") or fsx_pvc_name_of(mount_id, access="rw")
    pvc_ro = target.get("pvc_name_ro") or fsx_pvc_name_of(mount_id, access="ro")
    pv_rw = target.get("pv_name") or fsx_pv_name_of(str(ws_id), mount_id, access="rw")
    pv_ro = fsx_pv_name_of(str(ws_id), mount_id, access="ro")

    # force=False 时检查 pod 占用 (rw + ro 两个 PVC 都查)
    if not force and namespace:
        occupying: list[Any] = []
        for pvc_check in (pvc_rw, pvc_ro):
            try:
                pods = await k8s.list_pods_using_pvc(namespace, pvc_check)
            except K8sAPIError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"K8s list pods failed [{exc.code}]: {exc.message}",
                ) from exc
            occupying.extend(pods)
        if occupying:
            pod_names = [
                (p.get("metadata") or {}).get("name") for p in occupying
            ]
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"{len(occupying)} pod(s) still using FSx mount '{mount_id}': "
                    f"{', '.join(filter(None, pod_names))}. "
                    "Use ?force=true to detach anyway (pods will get IO errors)."
                ),
            )

    # 删两套 PVC + PV
    if namespace:
        for pvc_ in (pvc_rw, pvc_ro):
            try:
                await k8s.delete_pvc(namespace, pvc_)
            except K8sAPIError as exc:
                logger.warning(
                    "workspace.fsx.detach.pvc_fail",
                    ws_id=ws_id, pvc=pvc_, err=str(exc),
                )
    for pv_ in (pv_rw, pv_ro):
        try:
            await k8s.delete_pv(pv_)
        except K8sAPIError as exc:
            logger.warning(
                "workspace.fsx.detach.pv_fail",
                ws_id=ws_id, pv=pv_, err=str(exc),
            )

    # 改 DDB metadata.fsx_mounts (按 idx 删, 避免同 fs 多 subdir 误删别的)
    new_mounts = [m for i, m in enumerate(existing_mounts) if i != target_idx]
    new_metadata = dict(metadata)
    new_metadata["fsx_mounts"] = new_mounts
    # 删光所有 FSx 挂载 → 清 primary_gid (下次第一次挂载重新固化, 设计 §2.1).
    # 否则残留旧 gid, 重新挂别 team 目录时 runAsGroup 还用老 team 的 gid.
    if not new_mounts:
        new_metadata.pop("primary_gid", None)
    await ws_repo.update_workspace(ws_id, metadata=new_metadata)

    # 级联删该挂载的所有授权记录 (设计 §5.4)
    try:
        deleted = await mount_perms_repo.delete_by_mount(str(ws_id), mount_id)
        logger.info(
            "workspace.fsx.detach.perms_cascaded",
            ws_id=ws_id, mount_id=mount_id, count=deleted,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "workspace.fsx.detach.perms_cascade_fail",
            ws_id=ws_id, mount_id=mount_id, err=str(exc),
        )

    # AuditLog
    actor = current_user
    actor_username = str(actor.get("username") or actor.get("user_id") or "")
    try:
        await audit_repo.append(
            scope_key=ddb_tables.scope_key_workspace(str(ws_id)),
            actor_user_id=actor_username,
            actor_role="platform-admin",
            operation="workspace.fsx.detach",
            target_type="workspace",
            target_id=str(ws_id),
            status="succeeded",
            metadata={
                "mount_id": mount_id,
                "filesystem_id": filesystem_id,
                "pv_name_rw": pv_rw,
                "pv_name_ro": pv_ro,
                "pvc_name_rw": pvc_rw,
                "pvc_name_ro": pvc_ro,
                "force": force,
                "actor_email": actor.get("email") or "",
            },
        )
    except Exception as audit_exc:  # pragma: no cover
        logger.warning(
            "workspace.fsx.detach.audit_fail", ws_id=ws_id, err=str(audit_exc)
        )

    logger.info(
        "workspace.fsx.detach.ok",
        ws_id=ws_id, mount_id=mount_id, fs_id=filesystem_id, force=force,
    )
    return await list_workspace_fsx_flow(ws_id)


# list 子目录/文件走常驻 fsx-admin Deployment (一个 pod 挂多块盘, 每块 /fsx-mnt/<fs-id>)。
# 位置由 settings 配 (fsx_admin_namespace/label_selector/container); 部署见
# cluster-prereq.sh step_fsxadmin。Deployment pod 名带 hash, 按 label 查。
# 多 FSx: 挂载根 = /fsx-mnt/<fs-id> (规整后不再单块 /fsx; fs-id 天然路径安全)。
_FSX_MNT_BASE = "/fsx-mnt"


def _fsx_admin_root(filesystem_id: str) -> str:
    """拼 fsx-admin pod 内挂载根 /fsx-mnt/<fs-id>。

    未配 (不在 PLATFORM_FSX_FILESYSTEMS) → 抛 ValueError。
    """
    from app.adapters.aws import fsx as _fsx_adapter
    if not _fsx_adapter.is_configured_filesystem(filesystem_id):
        raise ValueError(
            t("workspace.fsx_not_configured", filesystem_id=filesystem_id)
        )
    return f"{_FSX_MNT_BASE}/{filesystem_id}"


async def _resolve_fsx_admin_pod(client: K8sClient) -> tuple[str, str, str] | None:
    """按 settings label 查 Running 的 admin pod, 返 (ns, pod_name, container).

    Deployment pod 名带随机后缀, 按 label 找 Running 的那个. 找不到返 None.
    """
    from app.core.config import get_settings

    settings = get_settings()
    ns = settings.fsx_admin_namespace
    selector = settings.fsx_admin_label_selector
    container = settings.fsx_admin_container
    try:
        pods = await client.list_pods_by_label_selector(ns, selector)
    except Exception as exc:  # noqa: BLE001
        logger.info("workspace.fsx.admin_pod.lookup_fail", err=str(exc))
        return None
    running = [
        p for p in pods if ((p.get("status") or {}).get("phase")) == "Running"
    ]
    target = running[0] if running else (pods[0] if pods else None)
    if not target:
        return None
    name = ((target.get("metadata") or {}).get("name")) or ""
    if not name:
        return None
    return ns, name, container


def _sanitize_fsx_subpath(path: str) -> str:
    """规整列目录 path: 去首尾斜杠, 拒 .. / 绝对路径 (防穿出 /fsx 列别处).

    返回安全的相对子路径 (可空). 非法段抛 ValueError.
    """
    p = (path or "").strip().strip("/")
    if not p:
        return ""
    segs = [s for s in p.split("/") if s]
    for s in segs:
        if s in ("..", ".") or "\x00" in s:
            raise ValueError(t("workspace.invalid_path_segment", segment=repr(s)))
    return "/".join(segs)


async def list_fsx_directories_flow(
    filesystem_id: str, path: str = ""
) -> list[dict[str, Any]]:
    """List immediate subdirs under /fsx-mnt/<fs-id>[/<path>] with their POSIX gid.

    多 FSx: 按 `filesystem_id` 定位, 该盘挂在 fsx-admin pod 的 /fsx-mnt/<fs-id>。
    `path` (相对该盘根, 空=根) 给训练代码目录级联铺路. 任何失败返空 list, 前端退化为自由文本.
    """
    try:
        fs_root = _fsx_admin_root(filesystem_id)
    except ValueError:
        logger.info("workspace.fsx.list_dirs.no_alias", fs_id=filesystem_id)
        return []
    safe_path = _sanitize_fsx_subpath(path)
    list_root = f"{fs_root}/{safe_path}" if safe_path else fs_root
    client = K8sClient()
    resolved = await _resolve_fsx_admin_pod(client)
    if not resolved:
        logger.info("workspace.fsx.list_dirs.no_admin_pod")
        return []
    ns, pod_name, container = resolved
    # 用纯 shell glob + `ls -ldn` 取 gid (第 4 列): amazonlinux:2023 minimal
    # 镜像没 find / stat, busybox 也只有 ls. 输出格式: "<name>|<gid>"
    out = await client.exec_in_pod(
        namespace=ns,
        pod_name=pod_name,
        container=container,
        command=[
            "sh", "-c",
            f'for d in "{list_root}"/*/; do '
            '[ -d "$d" ] && printf "%s|%s\\n" '
            '"$(basename "$d")" "$(ls -ldn "$d" | awk \'{print $4}\')"; '
            "done",
        ],
        timeout=5,
    )
    if not out:
        logger.info("workspace.fsx.list_dirs.empty_or_failed")
        return []

    result: list[dict[str, Any]] = []
    for line in out.strip().splitlines():
        if "|" not in line:
            continue
        name, gid_str = line.rsplit("|", 1)
        try:
            gid = int(gid_str.strip())
        except ValueError:
            continue
        name = name.strip()
        if name:
            result.append({"name": name, "gid": gid})
    return result


async def list_fsx_files_flow(
    filesystem_id: str, path: str = ""
) -> list[dict[str, Any]]:
    """List regular files (非目录) directly under /fsx-mnt/<fs-id>[/<path>].

    给训练任务"启动文件"下拉用: 选定代码子目录后列其下文件 (train.py 等).
    多 FSx: 按 `filesystem_id` → /fsx-mnt/<fs-id>, `path` 相对该盘根 (空=根).
    Returns empty list on failure so the UI can degrade to free-text.
    """
    try:
        fs_root = _fsx_admin_root(filesystem_id)
    except ValueError:
        logger.info("workspace.fsx.list_files.no_alias", fs_id=filesystem_id)
        return []
    safe_path = _sanitize_fsx_subpath(path)
    list_root = f"{fs_root}/{safe_path}" if safe_path else fs_root
    client = K8sClient()
    resolved = await _resolve_fsx_admin_pod(client)
    if not resolved:
        logger.info("workspace.fsx.list_files.no_admin_pod")
        return []
    ns, pod_name, container = resolved
    # 列普通文件 (-f): for f in dir/*; [ -f "$f" ] && basename. 输出 "<name>"
    out = await client.exec_in_pod(
        namespace=ns,
        pod_name=pod_name,
        container=container,
        command=[
            "sh", "-c",
            f'for f in "{list_root}"/*; do '
            '[ -f "$f" ] && basename "$f"; '
            "done",
        ],
        timeout=5,
    )
    if not out:
        logger.info("workspace.fsx.list_files.empty_or_failed")
        return []
    return [
        {"name": ln.strip()}
        for ln in out.strip().splitlines()
        if ln.strip()
    ]


def _parse_gid_from_ls(ls_dn_line: str) -> int | None:
    """从 `ls -ldn <dir>` 输出的一行取 gid (第 4 列, numeric).

    格式: drwxrws--- 2 <uid> <gid> <size> <date> <name>
    """
    parts = ls_dn_line.split()
    if len(parts) < 4:
        return None
    try:
        return int(parts[3])
    except ValueError:
        return None


async def probe_dir_gid(path: str) -> int | None:
    """exec fsx-admin pod 跑 `ls -ldn <path>` 探测目录真实 gid (main: cross-team).

    探测不到 (目录不存在 / pod 找不到 / exec 失败) 返 None, 调用方据此报错.
    子目录 gid 可能 ≠ 父目录, 必须探测真值 (设计 §5.1).
    复用 _resolve_fsx_admin_pod (merge: 统一 pod 解析).
    """
    client = K8sClient()
    resolved = await _resolve_fsx_admin_pod(client)
    if not resolved:
        logger.info("workspace.fsx.probe_gid.no_admin_pod")
        return None
    ns, pod_name, container = resolved
    out = await client.exec_in_pod(
        namespace=ns,
        pod_name=pod_name,
        container=container,
        command=["sh", "-c", f'ls -ldn "{path}"'],
        timeout=5,
    )
    if not out or not out.strip():
        return None
    return _parse_gid_from_ls(out.strip().splitlines()[0])
