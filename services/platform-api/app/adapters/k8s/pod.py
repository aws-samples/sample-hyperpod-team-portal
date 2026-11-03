"""Pod 查询 + exec 适配器.

职责:
    - 按 label selector 查 Pod (workspace 代理 + SSM id 提取等场景)
    - 在 Pod container 里 exec 任意命令 / cat 文件, 失败返 None 不抛

对应 K8s 资源:
    core/v1 Pod (内建资源, 非 CR)

官方 URL:
    https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.31/#pod-v1-core
    https://kubernetes.io/docs/tasks/debug/debug-application/get-shell-running-container/
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.exceptions import ApiException

from app.core.logging import get_logger

from .base import K8sClientBase, _to_primitive
from .errors import K8sAPIError

logger = get_logger(__name__)


class PodMixin(K8sClientBase):
    """core/v1 Pod 查询 + exec."""

    async def get_pod_by_workspace(
        self, namespace: str, workspace_name: str
    ) -> dict[str, Any] | None:
        """按 label jupyter.org/workspace-name=<workspace_name> 查 Pod.

        operator 在 Deployment 的 Pod template 里会打这个 label.
        返 Pod 的 dict (非 model). 没找到返 None.
        """
        try:
            await self._load_config()
            async with ApiClient() as api:
                v1 = k8s_client.CoreV1Api(api)
                resp = await v1.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=(
                        f"workspace.jupyter.org/workspace-name={workspace_name}"
                    ),
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        items = _to_primitive(resp).get("items", [])
        # 优先选 Running 的
        running = [
            p
            for p in items
            if (p.get("status") or {}).get("phase") == "Running"
        ]
        if running:
            return running[0]
        return items[0] if items else None

    async def get_ssh_service_hostname(
        self, namespace: str, workspace_name: str
    ) -> str | None:
        """读 directSSH 的固定 DNS 名.

        spaces addon 开 directSSH 后, 给每台开发机建一个 headless Service
        `ssh-<workspace_name>`, 上面打 external-dns 的 hostname 注解:
            external-dns.alpha.kubernetes.io/hostname: <ws>.<ns>.<domain>
        external-dns 据此在私有 zone 建 A 记录指向 pod IP.

        这里直接读注解拿最终 DNS 名 (而非自己拼 <ws>.<ns>.<domain>): addon
        改 DNS 规则时无需动代码。没有该 Service / 注解时返 None (未开 directSSH
        或 pod 未就绪), 上层按"暂不可连"处理。
        """
        try:
            await self._load_config()
            async with ApiClient() as api:
                v1 = k8s_client.CoreV1Api(api)
                svc = await v1.read_namespaced_service(
                    name=f"ssh-{workspace_name}", namespace=namespace
                )
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        meta = (_to_primitive(svc).get("metadata") or {})
        annotations = meta.get("annotations") or {}
        host = annotations.get("external-dns.alpha.kubernetes.io/hostname")
        return host or None

    async def list_pods_by_workspace(
        self, namespace: str, workspace_name: str
    ) -> list[dict[str, Any]]:
        """按 label workspace.jupyter.org/workspace-name=<name> 列该开发机的全部 Pod。

        返回 dict 列表 (供调用方按 creationTimestamp 取最新)。没找到返 []。
        """
        try:
            await self._load_config()
            async with ApiClient() as api:
                v1 = k8s_client.CoreV1Api(api)
                resp = await v1.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=(
                        f"workspace.jupyter.org/workspace-name={workspace_name}"
                    ),
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        return _to_primitive(resp).get("items", [])

    async def list_pods_by_label_selector(
        self, namespace: str, selector: str
    ) -> list[dict[str, Any]]:
        """Generic label-selector pod list (e.g. `workspace-name=foo`)."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                core = k8s_client.CoreV1Api(api)
                resp = await core.list_namespaced_pod(
                    namespace=namespace, label_selector=selector
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        items = resp.items or []
        return [p.to_dict() if hasattr(p, "to_dict") else p for p in items]

    async def exec_in_pod(
        self,
        namespace: str,
        pod_name: str,
        container: str,
        command: list[str],
        timeout: int = 5,
    ) -> str | None:
        """Run an arbitrary command inside a container, return stdout.

        Returns None on any failure (pod missing, container missing, non-zero
        exit, network flake) — intended for best-effort probes like agent
        health checks where we'd rather degrade than raise.
        """
        from kubernetes_asyncio.stream import WsApiClient

        try:
            await self._load_config()
            async with WsApiClient() as api:
                v1 = k8s_client.CoreV1Api(api)
                resp = await v1.connect_get_namespaced_pod_exec(
                    name=pod_name,
                    namespace=namespace,
                    container=container,
                    command=command,
                    stderr=True,
                    stdin=False,
                    stdout=True,
                    tty=False,
                    _request_timeout=timeout,
                )
        except ApiException as exc:
            logger.info(
                "k8s.exec_in_pod.fail",
                pod=pod_name,
                container=container,
                status=exc.status,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.info("k8s.exec_in_pod.unexpected", err=str(exc))
            return None
        if isinstance(resp, bytes):
            resp = resp.decode("utf-8", errors="replace")
        return resp or None

    async def read_pod_file(
        self,
        namespace: str,
        pod_name: str,
        container: str,
        path: str,
        timeout: int = 5,
    ) -> str | None:
        """exec `cat <path>` 到 pod container, 返 stdout 字符串.

        读失败(文件不存在/pod 没 ready) 返 None 不抛.
        用于读 ssm-agent-sidecar 的 /var/lib/amazon/ssm/registration JSON.
        """
        from kubernetes_asyncio.stream import WsApiClient

        try:
            await self._load_config()
            async with WsApiClient() as api:
                v1 = k8s_client.CoreV1Api(api)
                resp = await v1.connect_get_namespaced_pod_exec(
                    name=pod_name,
                    namespace=namespace,
                    container=container,
                    command=["cat", path],
                    stderr=True,
                    stdin=False,
                    stdout=True,
                    tty=False,
                    _request_timeout=timeout,
                )
        except ApiException as exc:
            logger.info(
                "k8s.read_pod_file.fail",
                pod=pod_name,
                path=path,
                status=exc.status,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.info("k8s.read_pod_file.unexpected", err=str(exc))
            return None
        if isinstance(resp, bytes):
            resp = resp.decode("utf-8", errors="replace")
        return resp or None

    async def stream_pod_logs(
        self,
        namespace: str,
        pod_name: str,
        container: str | None = None,
        tail_lines: int | None = 200,
        since_seconds: int | None = None,
    ) -> AsyncIterator[str]:
        """流式拉 Pod stdout (kubectl logs --follow 等价).

        实时训练日志专用 · 走 SSE / WebSocket 上层. Pod 没死 → 一直 yield 行;
        Pod 退出 → stream 关. 上层 cancel (浏览器关 SSE) 才停.

        Args:
            namespace: Pod 所在 ns
            pod_name: Pod 名
            container: 多容器 Pod 必传 (训练 Pod = "trainer")
            tail_lines: 起始尾行数 (默 200, None=从头)
            since_seconds: 仅取 N 秒内日志 (跟 tail_lines 二选一)

        Yields:
            一行日志 (rstrip 末尾 \\n).
        """
        await self._load_config()
        async with ApiClient() as api:
            v1 = k8s_client.CoreV1Api(api)
            kwargs: dict[str, Any] = {
                "name": pod_name,
                "namespace": namespace,
                "follow": True,
                "_preload_content": False,
            }
            if container:
                kwargs["container"] = container
            if tail_lines is not None:
                kwargs["tail_lines"] = tail_lines
            if since_seconds is not None:
                kwargs["since_seconds"] = since_seconds

            try:
                resp = await v1.read_namespaced_pod_log(**kwargs)
            except ApiException as exc:
                logger.info(
                    "k8s.stream_pod_log.api_fail",
                    pod=pod_name,
                    ns=namespace,
                    status=exc.status,
                )
                return

            try:
                async for line in resp.content:
                    text = line.decode("utf-8", errors="replace").rstrip("\n")
                    yield text
            except Exception as exc:  # noqa: BLE001
                logger.info(
                    "k8s.stream_pod_log.read_fail",
                    pod=pod_name,
                    err=str(exc),
                )
            finally:
                if hasattr(resp, "close"):
                    resp.close()

    async def exec_interactive(
        self,
        namespace: str,
        pod_name: str,
        container: str,
        command: list[str],
    ):
        """开交互式 exec (stdin+stdout+stderr+tty), 返回 aiohttp WebSocket 上下文管理器。

        k8s channel 协议 (上层 pump 用): 每帧首字节是 channel —
        0=stdin 1=stdout 2=stderr 3=err 4=resize。send: b'\\x00'+输入; recv: data[0] 判通道。
        交互式 terminal。调用方 `async with` 进 ws, 双向 pump 到浏览器。
        """
        from kubernetes_asyncio.stream import WsApiClient

        await self._load_config()
        api = WsApiClient()
        v1 = k8s_client.CoreV1Api(api)
        return await v1.connect_get_namespaced_pod_exec(
            name=pod_name,
            namespace=namespace,
            container=container,
            command=command,
            stderr=True,
            stdin=True,
            stdout=True,
            tty=True,
            _preload_content=False,
        )
