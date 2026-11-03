"""Workspace 配套 K8s 资源的写操作 (PV/PVC/SA/Role/RoleBinding).

职责:
    给 workspace 模块创建/删除流提供写能力. AWS HyperPod taskgovernance add-on
    自动建好 namespace + Kueue queue + ResourceQuota, 我们补这 5 件:

    - PersistentVolume (cluster-scoped, claimRef 锁定 ns/pvc 实现"别 ns 抢不走")
    - PersistentVolumeClaim (在 ws 的 ns, volumeName 双向绑 PV)
    - ServiceAccount workspace-default (ns 内, 给 pod 用)
    - Role workspace-developer (ns 内, 限定本 ns 资源)
    - RoleBinding (绑 SA → Role)

"""

from __future__ import annotations

from typing import Any

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.exceptions import ApiException

from app.core.logging import get_logger

from .base import K8sClientBase, _to_primitive
from .errors import K8sAPIError

logger = get_logger(__name__)


# 命名约定 (统一在这里, 避免散落字面量)
SA_NAME = "workspace-default"
ROLE_NAME = "workspace-developer"
ROLE_BINDING_NAME = "workspace-default-developer"
PV_LABEL_MANAGED = "hyperpod.platform/managed"
PV_LABEL_WORKSPACE = "hyperpod.platform/workspace"
PV_LABEL_FILESYSTEM = "hyperpod.platform/filesystem-id"
PV_ANNOTATION_SUBDIR = "hyperpod.platform/subdir"


# mount_id 用户填的别名 · 校验在 API schema 层做 (^[a-z][a-z0-9-]{2,39}$)
# 这里命名函数只拼前缀, 不再做 sanitize (mount_id 已经是 DNS-1123 安全字符)
def fsx_pv_name(workspace_id: str, mount_id: str, *, access: str = "rw") -> str:
    """FSx PV 名: pv-ws-<workspace_id>-fsx-<mount_id>-<access>."""
    return f"pv-ws-{workspace_id}-fsx-{mount_id}-{access}"


def fsx_pvc_name(mount_id: str, *, access: str = "rw") -> str:
    """FSx PVC 名: pvc-ws-fsx-<mount_id>-<access> (ws ns 内唯一)."""
    return f"pvc-ws-fsx-{mount_id}-{access}"


def s3_pv_name(workspace_id: str, mount_id: str) -> str:
    """S3 PV 名: pv-ws-<workspace_id>-s3-<mount_id>."""
    return f"pv-ws-{workspace_id}-s3-{mount_id}"


def s3_pvc_name(mount_id: str) -> str:
    """S3 PVC 名: pvc-ws-s3-<mount_id> (ws ns 内唯一)."""
    return f"pvc-ws-s3-{mount_id}"


def _is_already_exists(exc: ApiException) -> bool:
    return exc.status == 409 or "AlreadyExists" in (exc.reason or "")


def _is_not_found(exc: ApiException) -> bool:
    return exc.status == 404


class WorkspaceResourcesMixin(K8sClientBase):
    """Workspace 配套资源 CRUD."""

    # ===== ServiceAccount =====

    async def create_workspace_service_account(
        self,
        namespace: str,
        workspace_name: str,
    ) -> None:
        """在 ns 里建 workspace-default SA (幂等). 不打 IAM annotation;
        Pod Identity 走 EKS API CreatePodIdentityAssociation 关联, 不依赖 SA annotation."""
        body = k8s_client.V1ServiceAccount(
            metadata=k8s_client.V1ObjectMeta(
                name=SA_NAME,
                namespace=namespace,
                labels={
                    PV_LABEL_MANAGED: "true",
                    PV_LABEL_WORKSPACE: workspace_name,
                },
            ),
        )
        await self._load_config()
        async with ApiClient() as api:
            v1 = k8s_client.CoreV1Api(api)
            try:
                await v1.create_namespaced_service_account(
                    namespace=namespace, body=body
                )
            except ApiException as exc:
                if _is_already_exists(exc):
                    logger.info(
                        "k8s.sa.exists", ns=namespace, name=SA_NAME
                    )
                    return
                raise K8sAPIError(
                    f"ApiException.{exc.status}", exc.reason or str(exc)
                ) from exc
        logger.info("k8s.sa.created", ns=namespace, name=SA_NAME)

    async def delete_workspace_service_account(self, namespace: str) -> None:
        """删 SA (NotFound 容忍)."""
        await self._load_config()
        async with ApiClient() as api:
            v1 = k8s_client.CoreV1Api(api)
            try:
                await v1.delete_namespaced_service_account(
                    namespace=namespace, name=SA_NAME
                )
            except ApiException as exc:
                if _is_not_found(exc):
                    return
                raise K8sAPIError(
                    f"ApiException.{exc.status}", exc.reason or str(exc)
                ) from exc

    # ===== Role + RoleBinding =====

    async def create_workspace_role_and_binding(
        self,
        namespace: str,
        workspace_name: str,
    ) -> None:
        """建 Role + RoleBinding (幂等).

        Role 给 SA workspace-default 限定本 ns 内的:
            - core/v1: pods, pods/log, pods/exec, services, configmaps, pvc
            - batch/v1: jobs
            - kueue.x-k8s.io: workloads, localqueues (查队列状态)
        不允许动 ResourceQuota / NetworkPolicy / 跨 ns.
        """
        labels = {
            PV_LABEL_MANAGED: "true",
            PV_LABEL_WORKSPACE: workspace_name,
        }

        role = k8s_client.V1Role(
            metadata=k8s_client.V1ObjectMeta(
                name=ROLE_NAME, namespace=namespace, labels=labels
            ),
            rules=[
                k8s_client.V1PolicyRule(
                    api_groups=[""],
                    resources=[
                        "pods",
                        "pods/log",
                        "pods/exec",
                        "services",
                        "configmaps",
                        "persistentvolumeclaims",
                    ],
                    verbs=["get", "list", "watch", "create", "delete"],
                ),
                k8s_client.V1PolicyRule(
                    api_groups=["batch"],
                    resources=["jobs"],
                    verbs=["get", "list", "watch", "create", "delete"],
                ),
                k8s_client.V1PolicyRule(
                    api_groups=["kueue.x-k8s.io"],
                    resources=["workloads", "localqueues"],
                    verbs=["get", "list", "watch"],
                ),
            ],
        )

        role_binding = k8s_client.V1RoleBinding(
            metadata=k8s_client.V1ObjectMeta(
                name=ROLE_BINDING_NAME, namespace=namespace, labels=labels
            ),
            subjects=[
                k8s_client.RbacV1Subject(
                    kind="ServiceAccount",
                    name=SA_NAME,
                    namespace=namespace,
                )
            ],
            role_ref=k8s_client.V1RoleRef(
                kind="Role",
                name=ROLE_NAME,
                api_group="rbac.authorization.k8s.io",
            ),
        )

        await self._load_config()
        async with ApiClient() as api:
            rbac = k8s_client.RbacAuthorizationV1Api(api)
            try:
                await rbac.create_namespaced_role(namespace=namespace, body=role)
            except ApiException as exc:
                if not _is_already_exists(exc):
                    raise K8sAPIError(
                        f"ApiException.{exc.status}", exc.reason or str(exc)
                    ) from exc
            try:
                await rbac.create_namespaced_role_binding(
                    namespace=namespace, body=role_binding
                )
            except ApiException as exc:
                if not _is_already_exists(exc):
                    raise K8sAPIError(
                        f"ApiException.{exc.status}", exc.reason or str(exc)
                    ) from exc
        logger.info("k8s.role_and_binding.created", ns=namespace)

    async def delete_workspace_role_and_binding(self, namespace: str) -> None:
        """删 Role + RoleBinding (NotFound 容忍)."""
        await self._load_config()
        async with ApiClient() as api:
            rbac = k8s_client.RbacAuthorizationV1Api(api)
            for delete_call in (
                lambda: rbac.delete_namespaced_role_binding(
                    namespace=namespace, name=ROLE_BINDING_NAME
                ),
                lambda: rbac.delete_namespaced_role(
                    namespace=namespace, name=ROLE_NAME
                ),
            ):
                try:
                    await delete_call()
                except ApiException as exc:
                    if _is_not_found(exc):
                        continue
                    raise K8sAPIError(
                        f"ApiException.{exc.status}", exc.reason or str(exc)
                    ) from exc

    # ===== PV (cluster-scoped) =====

    async def create_fsx_pv(
        self,
        *,
        workspace_id: str,
        workspace_name: str,
        namespace: str,
        filesystem_id: str,
        dns_name: str,
        mount_name: str,
        capacity_gib: int,
        mount_id: str,
        subdir: str = "",
        storage_class: str = "fsx-sc",
        access: str = "rw",
    ) -> str:
        """建 PV 引用 FSx Lustre, claimRef 锁定 ns/pvc.

        命名: pv-ws-{ws_id}-fsx-{mount_id}, 前端用户填 mount_id (DNS-1123 合法).
        - reclaimPolicy=Retain: PV 删了不动 FSx 数据
        - claimRef: 反向绑定到指定 ns/pvc, 别 ns 抢不走
        - subdir: 子目录隔离靠 mountname 拼子路径 (mountname=<lustre-mount>/<subdir>),
          Lustre 客户端只挂该子目录, 容器看不到 FSx 根 (其他 team 的目录).
          不能靠 pod volumeMounts.subPath — SageMaker Spaces operator 0.0.16 的
          Workspace CRD spec.volumes[] 不认 subPath 字段, 会被 structural prune 静默丢弃.
          volumeHandle 必须全集群唯一: 用 ws_id + mount_id + access 区分, 裸 filesystem_id
          会撞 (FSx CSI 把 volumeHandle 当 volume id, 重了第二个 PV 挂不上). 带 ws_id 防
          跨 ws 同名 mount_id 撞车 (同一块 FSx 被多个 ws 挂).
        """
        name = fsx_pv_name(workspace_id, mount_id, access=access)
        annotations = {PV_ANNOTATION_SUBDIR: subdir} if subdir else None
        # 子目录隔离: Lustre mountname 后拼 subdir, driver 只挂该子目录
        full_mount_name = f"{mount_name}/{subdir}" if subdir else mount_name
        body = k8s_client.V1PersistentVolume(
            metadata=k8s_client.V1ObjectMeta(
                name=name,
                labels={
                    PV_LABEL_MANAGED: "true",
                    PV_LABEL_WORKSPACE: workspace_name,
                    PV_LABEL_FILESYSTEM: filesystem_id,
                },
                annotations=annotations,
            ),
            spec=k8s_client.V1PersistentVolumeSpec(
                capacity={"storage": f"{capacity_gib}Gi"},
                volume_mode="Filesystem",
                access_modes=["ReadWriteMany"],
                persistent_volume_reclaim_policy="Retain",
                storage_class_name=storage_class,
                # relatime: 减少 atime 写放大 (首读更新, 24h 内再读不更新); Lustre 默认
                # strictatime 每次读都写 atime, 训练海量读场景浪费 IO。已实测 Lustre 认
                # 此选项 (/proc/mounts 生效 + relatime 语义正确)。
                # ro 靠 mountOptions:[ro] (只有 mountOptions 在 Lustre CSI 真拦写;
                # csi.readOnly 无效)。
                mount_options=(
                    ["relatime", "ro"] if access == "ro" else ["relatime"]
                ),
                csi=k8s_client.V1CSIPersistentVolumeSource(
                    driver="fsx.csi.aws.com",
                    # volumeHandle 必须全集群唯一: 带 ws_id 防跨 ws 同名 mount_id 撞车
                    # (同一块 FSx 被多个 ws 挂、且 mount_id 取了相同名时, 少了 ws_id
                    # 会让 FSx CSI 把两个 PV 当成同一个卷, 第二个挂不上).
                    volume_handle=f"{filesystem_id}-{workspace_id}-{mount_id}-{access}",
                    volume_attributes={
                        "dnsname": dns_name,
                        "mountname": full_mount_name,
                    },
                ),
                claim_ref=k8s_client.V1ObjectReference(
                    namespace=namespace,
                    name=fsx_pvc_name(mount_id, access=access),
                ),
            ),
        )
        await self._load_config()
        async with ApiClient() as api:
            v1 = k8s_client.CoreV1Api(api)
            try:
                await v1.create_persistent_volume(body=body)
            except ApiException as exc:
                if _is_already_exists(exc):
                    logger.info("k8s.pv.exists", name=name)
                    return name
                raise K8sAPIError(
                    f"ApiException.{exc.status}", exc.reason or str(exc)
                ) from exc
        logger.info("k8s.pv.created", name=name, fs=filesystem_id, mount_id=mount_id)
        return name

    async def delete_pv(self, name: str) -> None:
        """删 PV (NotFound 容忍)."""
        await self._load_config()
        async with ApiClient() as api:
            v1 = k8s_client.CoreV1Api(api)
            try:
                await v1.delete_persistent_volume(name=name)
            except ApiException as exc:
                if _is_not_found(exc):
                    return
                raise K8sAPIError(
                    f"ApiException.{exc.status}", exc.reason or str(exc)
                ) from exc

    # ===== PVC =====

    async def create_fsx_pvc(
        self,
        *,
        namespace: str,
        workspace_name: str,
        filesystem_id: str,
        pv_full_name: str,
        capacity_gib: int,
        mount_id: str,
        storage_class: str = "fsx-sc",
        access: str = "rw",
    ) -> str:
        """建 PVC, 显式给 PV 名 (双向绑). 命名: pvc-ws-fsx-{mount_id}-{access}."""
        name = fsx_pvc_name(mount_id, access=access)
        body = k8s_client.V1PersistentVolumeClaim(
            metadata=k8s_client.V1ObjectMeta(
                name=name,
                namespace=namespace,
                labels={
                    PV_LABEL_MANAGED: "true",
                    PV_LABEL_WORKSPACE: workspace_name,
                    PV_LABEL_FILESYSTEM: filesystem_id,
                },
            ),
            spec=k8s_client.V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteMany"],
                storage_class_name=storage_class,
                resources=k8s_client.V1VolumeResourceRequirements(
                    requests={"storage": f"{capacity_gib}Gi"}
                ),
                volume_name=pv_full_name,
            ),
        )
        await self._load_config()
        async with ApiClient() as api:
            v1 = k8s_client.CoreV1Api(api)
            try:
                await v1.create_namespaced_persistent_volume_claim(
                    namespace=namespace, body=body
                )
            except ApiException as exc:
                if _is_already_exists(exc):
                    logger.info("k8s.pvc.exists", ns=namespace, name=name)
                    return name
                raise K8sAPIError(
                    f"ApiException.{exc.status}", exc.reason or str(exc)
                ) from exc
        logger.info("k8s.pvc.created", ns=namespace, name=name, mount_id=mount_id)
        return name

    async def delete_pvc(self, namespace: str, name: str) -> None:
        """删 PVC (NotFound 容忍)."""
        await self._load_config()
        async with ApiClient() as api:
            v1 = k8s_client.CoreV1Api(api)
            try:
                await v1.delete_namespaced_persistent_volume_claim(
                    namespace=namespace, name=name
                )
            except ApiException as exc:
                if _is_not_found(exc):
                    return
                raise K8sAPIError(
                    f"ApiException.{exc.status}", exc.reason or str(exc)
                ) from exc

    # ===== Pod 占用检查 (用于 force=false 时阻止 detach) =====

    async def list_pods_using_pvc(
        self, namespace: str, pvc_name_value: str
    ) -> list[dict[str, Any]]:
        """列出该 ns 内 spec.volumes 引用了指定 PVC 的 pod."""
        await self._load_config()
        async with ApiClient() as api:
            v1 = k8s_client.CoreV1Api(api)
            try:
                resp = await v1.list_namespaced_pod(namespace=namespace)
            except ApiException as exc:
                if _is_not_found(exc):
                    return []
                raise K8sAPIError(
                    f"ApiException.{exc.status}", exc.reason or str(exc)
                ) from exc
        data = _to_primitive(resp) if hasattr(resp, "to_dict") else resp
        items = data.get("items", []) or []
        result: list[dict[str, Any]] = []
        for pod in items:
            volumes = ((pod.get("spec") or {}).get("volumes")) or []
            for v in volumes:
                pvc = v.get("persistent_volume_claim") or v.get(
                    "persistentVolumeClaim"
                )
                if pvc and (pvc.get("claim_name") or pvc.get("claimName")) == pvc_name_value:
                    result.append(pod)
                    break
        return result

    # ===== S3 PV/PVC (Mountpoint S3 CSI) =====

    async def create_s3_pv(
        self,
        *,
        workspace_id: str,
        workspace_name: str,
        namespace: str,
        bucket_name: str,
        region: str,
        mount_id: str,
        prefix: str = "",
        capacity_gib: int = 1200,
        storage_class: str = "s3-sc",
    ) -> str:
        """建 PV 引用 S3 bucket (Mountpoint S3 CSI).

        命名: pv-ws-{ws_id}-s3-{mount_id}, 前端用户填 mount_id (DNS-1123 合法).
        真·只读: mountOptions 加 Mountpoint 原生 `read-only` flag → 拒绝一切写
        (含新建文件)。注意仅"不加 allow-overwrite/delete"还允许新建对象 (S3 PUT),
        必须显式 read-only 才彻底禁写。S3 挂载只用于读数据集/模型, 不作写入目标。
        """
        name = s3_pv_name(workspace_id, mount_id)

        # mountOptions: read-only (Mountpoint 原生 flag, 禁一切写含新建) + uid/gid 1000。
        # 只靠去掉 allow-overwrite/delete 不够 (仍可 touch 新文件); read-only 才真只读。
        mount_options = [
            "read-only",            # Mountpoint 真只读: 拒绝新建/覆盖/删除
            f"region {region}",
            "allow-other",          # FUSE 必需 (非 root pod 进程访问)
            "uid=1000",
            "gid=1000",
            "dir-mode=0755",
            "file-mode=0644",
            "metadata-ttl=300",     # 5min metadata 缓存 (减 S3 LIST 调用)
        ]
        if prefix:
            # Mountpoint 接受 prefix 但要求结尾带 /
            normalized_prefix = prefix if prefix.endswith("/") else f"{prefix}/"
            mount_options.append(f"prefix {normalized_prefix}")

        body = k8s_client.V1PersistentVolume(
            metadata=k8s_client.V1ObjectMeta(
                name=name,
                labels={
                    PV_LABEL_MANAGED: "true",
                    PV_LABEL_WORKSPACE: workspace_name,
                    "hyperpod.platform/s3-bucket": bucket_name,
                },
            ),
            spec=k8s_client.V1PersistentVolumeSpec(
                capacity={"storage": f"{capacity_gib}Gi"},
                volume_mode="Filesystem",
                access_modes=["ReadWriteMany"],
                persistent_volume_reclaim_policy="Retain",
                storage_class_name=storage_class,
                mount_options=mount_options,
                csi=k8s_client.V1CSIPersistentVolumeSource(
                    driver="s3.csi.aws.com",
                    # volumeHandle 全集群唯一; (ws_id, mount_id) 复合保证
                    volume_handle=f"s3-{workspace_id}-{name}",
                    volume_attributes={"bucketName": bucket_name},
                ),
                claim_ref=k8s_client.V1ObjectReference(
                    namespace=namespace,
                    name=s3_pvc_name(mount_id),
                ),
            ),
        )
        await self._load_config()
        async with ApiClient() as api:
            v1 = k8s_client.CoreV1Api(api)
            try:
                await v1.create_persistent_volume(body=body)
            except ApiException as exc:
                if _is_already_exists(exc):
                    logger.info("k8s.s3_pv.exists", name=name)
                    return name
                raise K8sAPIError(
                    f"ApiException.{exc.status}", exc.reason or str(exc)
                ) from exc
        logger.info(
            "k8s.s3_pv.created",
            name=name, bucket=bucket_name, prefix=prefix or "(root)", mount_id=mount_id,
        )
        return name

    async def create_s3_pvc(
        self,
        *,
        namespace: str,
        workspace_name: str,
        bucket_name: str,
        pv_full_name: str,
        mount_id: str,
        capacity_gib: int = 1200,
        storage_class: str = "s3-sc",
    ) -> str:
        """建 S3 PVC, 双向绑到 PV. 命名: pvc-ws-s3-{mount_id}."""
        name = s3_pvc_name(mount_id)
        body = k8s_client.V1PersistentVolumeClaim(
            metadata=k8s_client.V1ObjectMeta(
                name=name,
                namespace=namespace,
                labels={
                    PV_LABEL_MANAGED: "true",
                    PV_LABEL_WORKSPACE: workspace_name,
                    "hyperpod.platform/s3-bucket": bucket_name,
                },
            ),
            spec=k8s_client.V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteMany"],
                storage_class_name=storage_class,
                resources=k8s_client.V1VolumeResourceRequirements(
                    requests={"storage": f"{capacity_gib}Gi"}
                ),
                volume_name=pv_full_name,
            ),
        )
        await self._load_config()
        async with ApiClient() as api:
            v1 = k8s_client.CoreV1Api(api)
            try:
                await v1.create_namespaced_persistent_volume_claim(
                    namespace=namespace, body=body
                )
            except ApiException as exc:
                if _is_already_exists(exc):
                    logger.info("k8s.s3_pvc.exists", ns=namespace, name=name)
                    return name
                raise K8sAPIError(
                    f"ApiException.{exc.status}", exc.reason or str(exc)
                ) from exc
        logger.info(
            "k8s.s3_pvc.created", ns=namespace, name=name, mount_id=mount_id
        )
        return name
