"""共享挂载解析 · create / resize 共用 (DDB-only).

把"校验用户勾选的 FSx/S3 挂载合法 + PVC 真实存在 + 算 gid"抽成一处, 保证创建流和
改规格流对挂载的判定完全一致 (授权、PVC drift 校验、gid 计算不会分叉)。

安全 (API 已公网, agent 可能直接调): 用户只能挂自己被授权的 FSx (MountPermissions
GSI 成员级权限); S3 无成员级权限, 沿用 ws.metadata.s3_mounts。任何越权 mount_path 或
pvc_name 不符 → 400。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.adapters.k8s import K8sAPIError, K8sClient
from app.core.i18n import t
from app.core.logging import get_logger
from app.repositories import mount_permissions as mount_perms_repo

logger = get_logger(__name__)


async def resolve_mounts(
    k8s: K8sClient,
    *,
    ws_id: Any,
    k8s_ns: str,
    username: str,
    ws_md: dict[str, Any],
    volume_mounts: list[Any],
) -> tuple[list[dict[str, Any]], int | None, list[int]]:
    """校验勾选挂载 + 查 PVC 存在 + 算 gid。

    Args:
        volume_mounts: VolumeMount 列表 (需有 .mount_path / .pvc_name / .name 属性)。
        ws_md: workspace.metadata_json (取 s3_mounts + primary_gid)。
        username: 查 MountPermissions 的用户名 (成员级 FSx 授权)。

    Returns:
        (volume_mounts_json, primary_gid, supplemental_gids)
          - volume_mounts_json: [{"name","mount_path","pvc_name"}] 落 DDB + 渲染 CR。
          - primary_gid: ws 固有主 gid (runAsGroup/fsGroup); 没挂 FSx 时 None。
          - supplemental_gids: 本次实际勾选挂载的 gid 列表 (进 supplementalGroups)。

    Raises:
        HTTPException 400: mount_path 未授权 / pvc_name 不符。
        HTTPException 409: 勾选挂载的 PVC 在集群不存在 (drift)。
        HTTPException 502: 校验 PVC 时 K8s 调用失败。
    """
    perms = await mount_perms_repo.list_by_user_in_ws(ws_id, username)

    # mount_path → {kind, pvc_name}: FSx 走成员级权限, S3 走 ws.metadata。
    allowed_by_path: dict[str, dict[str, Any]] = {}
    for p in perms:
        access = p.get("access", "rw")
        pvc = (
            p.get("pvc_name_ro") if access == "ro" else p.get("pvc_name_rw")
        ) or p.get("pvc_name_rw")
        allowed_by_path[p.get("mount_path")] = {"kind": "fsx", "pvc_name": pvc}
    for m in ws_md.get("s3_mounts") or []:
        allowed_by_path[m["mount_path"]] = {"kind": "s3", "pvc_name": m["pvc_name"]}

    # 授权 + pvc_name 一致性校验
    for vm in (volume_mounts or []):
        expected = allowed_by_path.get(vm.mount_path)
        if expected is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"mount_path '{vm.mount_path}' not permitted; "
                f"only {list(allowed_by_path.keys())} allowed",
            )
        if expected["pvc_name"] != vm.pvc_name:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"pvc_name mismatch for {vm.mount_path} "
                f"(expected {expected['pvc_name']}, got {vm.pvc_name})",
            )

    # PVC 真实存在校验 (防 DDB 记了挂载但 K8s PVC 缺失 → pod 卡挂载失败)
    for vm in (volume_mounts or []):
        try:
            if not await k8s.pvc_exists(k8s_ns, vm.pvc_name):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    t(
                        "devinstance.mount_pvc_missing",
                        mount_path=vm.mount_path,
                        pvc_name=vm.pvc_name,
                    ),
                )
        except K8sAPIError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                t("devinstance.mount_pvc_check_failed", pvc_name=vm.pvc_name, message=exc.message),
            ) from exc

    volume_mounts_json = [
        {"name": vm.name, "mount_path": vm.mount_path, "pvc_name": vm.pvc_name}
        for vm in (volume_mounts or [])
    ]

    # primary_gid = ws 固有主 gid (runAsGroup); DDB number 反序列化是 Decimal, int(...) 兼容。
    primary_gid: int | None = None
    raw_primary = ws_md.get("primary_gid")
    if raw_primary is not None:
        try:
            primary_gid = int(raw_primary)
        except (TypeError, ValueError):
            logger.info("devinstance.mounts.primary_gid_parse_skip", raw=repr(raw_primary))

    # 只收集本次实际勾选挂载的 gid (perms 是全部被授权的, 按 selected 过滤)。
    selected_paths = {vm.mount_path for vm in (volume_mounts or [])}
    supplemental_gids: list[int] = []
    for p in perms:
        if p.get("mount_path") in selected_paths:
            gid_raw = p.get("gid")
            if gid_raw is not None:
                try:
                    supplemental_gids.append(int(gid_raw))
                except (TypeError, ValueError):
                    pass
    # ws 没 primary_gid (没挂过 FSx) 但挂了 share 目录时, 用第一个 supplemental 兜底。
    if primary_gid is None and supplemental_gids:
        primary_gid = supplemental_gids[0]

    return volume_mounts_json, primary_gid, supplemental_gids
