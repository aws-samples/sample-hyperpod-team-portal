"""通用 Secret 适配器 (supersedes).

职责:
    每人一把固定 k8s Secret (名 <owner>-secrets, 见 orchestration), 里面存多个
    key-value 凭证 (token/密码/任意). 用户只管 key-value, secret 名平台自动派生 (用户无感).
    训练等任务 env 用 secretKeyRef 引它 (env 值不进配置明文).

对应 K8s 资源:
    core/v1 Secret (Opaque). data = 多 key-value (k8s 侧 base64, 非加密 →
    安全靠 RBAC, 措施3).

单 key 增删走 read-modify-write (读现有 data → 改一个 key → 整体 replace),
不覆盖同 secret 其他 key。value 只写不回读 (get 只回 key 名)。
"""

from __future__ import annotations

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.exceptions import ApiException

from app.core.logging import get_logger

from .base import K8sClientBase
from .errors import K8sAPIError

logger = get_logger(__name__)

_MANAGED_LABEL = "platform.hyperpod.io/managed"
_MANAGED_VALUE = "user-secret"


class SecretMixin(K8sClientBase):
    """core/v1 Secret · 每人一把, 通用 key-value 凭证托管."""

    async def put_secret_key(
        self,
        namespace: str,
        name: str,
        key: str,
        value: str,
        *,
        annotations: dict[str, str] | None = None,
    ) -> list[str]:
        """加/改一个 key (secret 不存在则建)。返回改后全部 key 名。value 只写不回读。"""
        try:
            await self._load_config()
            async with ApiClient() as api:
                v1 = k8s_client.CoreV1Api(api)
                try:
                    existing = await v1.read_namespaced_secret(
                        name=name, namespace=namespace
                    )
                except ApiException as exc:
                    if exc.status != 404:
                        raise
                    existing = None
                if existing is None:
                    body = k8s_client.V1Secret(
                        metadata=k8s_client.V1ObjectMeta(
                            name=name,
                            namespace=namespace,
                            labels={_MANAGED_LABEL: _MANAGED_VALUE},
                            annotations=annotations or {},
                        ),
                        type="Opaque",
                        string_data={key: value},
                    )
                    await v1.create_namespaced_secret(namespace=namespace, body=body)
                    return [key]
                # 现有 data (base64) 原样保留, 新/改 key 走 string_data (k8s 编码后合并)
                existing.string_data = {key: value}
                await v1.replace_namespaced_secret(
                    name=name, namespace=namespace, body=existing
                )
                return sorted(set((existing.data or {}).keys()) | {key})
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc

    async def delete_secret_key(
        self, namespace: str, name: str, key: str
    ) -> list[str]:
        """删一个 key (read-modify-write)。secret/key 不存在视作已删 (幂等)。返回剩余 key 名。"""
        try:
            await self._load_config()
            async with ApiClient() as api:
                v1 = k8s_client.CoreV1Api(api)
                try:
                    existing = await v1.read_namespaced_secret(
                        name=name, namespace=namespace
                    )
                except ApiException as exc:
                    if exc.status == 404:
                        return []
                    raise
                data = dict(existing.data or {})
                if key not in data:
                    return sorted(data.keys())
                data.pop(key, None)
                existing.data = data
                existing.string_data = None
                await v1.replace_namespaced_secret(
                    name=name, namespace=namespace, body=existing
                )
                return sorted(data.keys())
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc

    async def get_secret_keys(self, namespace: str, name: str) -> list[str]:
        """读本人 secret 的 key 名 (不含 value)。不存在返 []。"""
        try:
            await self._load_config()
            async with ApiClient() as api:
                v1 = k8s_client.CoreV1Api(api)
                try:
                    s = await v1.read_namespaced_secret(name=name, namespace=namespace)
                except ApiException as exc:
                    if exc.status == 404:
                        return []
                    raise
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        return sorted((s.data or {}).keys())
