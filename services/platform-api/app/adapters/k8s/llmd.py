"""llm-d 资源适配器 (分支B)。

与 dynamo (单一 DynamoGraphDeployment CR) 不同, llm-d 一个服务 = 一组标准资源:
    ConfigMap / ServiceAccount / Role / RoleBinding / Deployment / Service / LeaderWorkerSet
故 adapter 按 kind 分发 apply/delete (非单 CR CRUD)。domain/cr.py 出 list[dict], 这里落地。

CRD: leaderworkersets.leaderworkerset.x-k8s.io/v1 (LWS operator 需预先装好, 见 deploy/cluster-prereq.sh 的 lws 步骤)。
"""

from __future__ import annotations

from typing import Any, Callable

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.exceptions import ApiException

from app.core.i18n import t
from app.core.logging import get_logger

from .base import K8sClientBase, _to_primitive
from .errors import K8sAPIError

logger = get_logger(__name__)

_LWS_GROUP = "leaderworkerset.x-k8s.io"
_LWS_VERSION = "v1"
_LWS_PLURAL = "leaderworkersets"


class LlmdMixin(K8sClientBase):
    """llm-d 一组资源的批量 apply/delete (按 kind 分发)。"""

    async def apply_llmd_resources(
        self, namespace: str, resources: list[dict[str, Any]]
    ) -> None:
        """按 kind 逐个 create (幂等: 已存在 409 → replace/跳过)。顺序照 domain 出的 list
        (ConfigMap → RBAC → Deployment → Service → [Ingress] → LWS)。"""
        await self._load_config()
        async with ApiClient() as api:
            core = k8s_client.CoreV1Api(api)
            apps = k8s_client.AppsV1Api(api)
            rbac = k8s_client.RbacAuthorizationV1Api(api)
            co = k8s_client.CustomObjectsApi(api)
            net = k8s_client.NetworkingV1Api(api)
            for r in resources:
                kind = r["kind"]
                name = r["metadata"]["name"]
                try:
                    await self._create_one(core, apps, rbac, co, net, namespace, kind, r)
                except ApiException as exc:
                    if exc.status == 409:  # 已存在 → replace (幂等重入)
                        await self._replace_one(core, apps, namespace, kind, name, r)
                        continue
                    logger.warning(
                        "k8s.apply_llmd.api_error", kind=kind, name=name,
                        status=exc.status, reason=exc.reason,
                        body=getattr(exc, "body", None),
                    )
                    raise K8sAPIError(
                        f"ApiException.{exc.status}",
                        f"{kind}/{name}: {exc.reason}: {getattr(exc, 'body', '')}",
                    ) from exc

    @staticmethod
    async def _create_one(core, apps, rbac, co, net, ns, kind, body):  # noqa: ANN001
        if kind == "ConfigMap":
            await core.create_namespaced_config_map(namespace=ns, body=body)
        elif kind == "ServiceAccount":
            await core.create_namespaced_service_account(namespace=ns, body=body)
        elif kind == "Service":
            await core.create_namespaced_service(namespace=ns, body=body)
        elif kind == "Ingress":
            # 409 时 _replace_one 跳过: 内容不变, 故 RBAC 无需 update 权限
            await net.create_namespaced_ingress(namespace=ns, body=body)
        elif kind == "Role":
            await rbac.create_namespaced_role(namespace=ns, body=body)
        elif kind == "RoleBinding":
            await rbac.create_namespaced_role_binding(namespace=ns, body=body)
        elif kind == "Deployment":
            await apps.create_namespaced_deployment(namespace=ns, body=body)
        elif kind == "LeaderWorkerSet":
            await co.create_namespaced_custom_object(
                group=_LWS_GROUP, version=_LWS_VERSION, namespace=ns,
                plural=_LWS_PLURAL, body=body,
            )
        else:
            raise K8sAPIError("UnsupportedKind", t("k8s.llmd_unsupported_kind", kind=kind))

    @staticmethod
    async def _replace_one(core, apps, ns, kind, name, body):  # noqa: ANN001
        # ConfigMap/Deployment replace; 其余 (Service/RBAC/SA/LWS) 已存在视幂等跳过
        if kind == "ConfigMap":
            await core.replace_namespaced_config_map(name=name, namespace=ns, body=body)
        elif kind == "Deployment":
            await apps.replace_namespaced_deployment(name=name, namespace=ns, body=body)

    async def delete_llmd_resources(self, namespace: str, name: str) -> None:
        """级联删一个 llm-d 服务的全部资源 (按 name 前缀), 单个 404 幂等, 尽力删完。"""
        await self._load_config()
        async with ApiClient() as api:
            core = k8s_client.CoreV1Api(api)
            apps = k8s_client.AppsV1Api(api)
            rbac = k8s_client.RbacAuthorizationV1Api(api)
            co = k8s_client.CustomObjectsApi(api)
            net = k8s_client.NetworkingV1Api(api)
            gw = f"{name}-gateway"
            deletes: list[Callable[[], Any]] = [
                # Ingress 排最前: 先摘入口再删后端, 免得中途 502。
                # 不挂 ownerReference: AWS 侧的 ALB/TG/SG 靠 controller 的 finalizer 回收
                lambda: net.delete_namespaced_ingress(
                    name=f"alb-{name}", namespace=namespace),
                lambda: co.delete_namespaced_custom_object(
                    group=_LWS_GROUP, version=_LWS_VERSION, namespace=namespace,
                    plural=_LWS_PLURAL, name=f"{name}-multi"),
                lambda: apps.delete_namespaced_deployment(name=gw, namespace=namespace),
                lambda: core.delete_namespaced_service(name=gw, namespace=namespace),
                lambda: rbac.delete_namespaced_role_binding(
                    name=f"{name}-gateway-rb", namespace=namespace),
                lambda: rbac.delete_namespaced_role(
                    name=f"{name}-gateway-role", namespace=namespace),
                lambda: core.delete_namespaced_service_account(
                    name=f"{name}-gateway-sa", namespace=namespace),
                lambda: core.delete_namespaced_config_map(
                    name=f"{name}-otel", namespace=namespace),
            ]
            for d in deletes:
                try:
                    await d()
                except ApiException as exc:
                    if exc.status == 404:
                        continue
                    logger.warning(
                        "k8s.delete_llmd.api_error", name=name, status=exc.status
                    )

    async def get_leaderworkerset(self, namespace: str, name: str) -> dict[str, Any]:
        """拉 LWS status (详情页 sync 用)。"""
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.get_namespaced_custom_object(
                    group=_LWS_GROUP, version=_LWS_VERSION, namespace=namespace,
                    plural=_LWS_PLURAL, name=name,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp
