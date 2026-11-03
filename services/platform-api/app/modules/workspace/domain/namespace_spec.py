"""Workspace K8s namespace 规范 (纯函数 / spec 生成).

范围说明 (决策固化)
=========================
workspace 模块**不直接渲染 K8s CR** · 由两侧分担:

1. **HyperPod team API (AWS 自动)** 在 CreateComputeQuota 之后自动产出:
   - `hyperpod-ns-<team>` Namespace
   - ResourceQuota (GPU/CPU/Memory 硬限)
   - Kueue ClusterQueue / LocalQueue + fair-share + preemption

2. **Phase 1 WorkspaceController (Go Operator, plan/22 L2)** 补足
   HyperPod 不覆盖的 5 项安全基线:
   - NetworkPolicy default-deny + 平台白名单
   - PSS Pod Security Standards `restricted` namespace label
   - ServiceAccount + EKS Pod Identity ABAC tag
   - 预缓存 Secret (uid/gid/fsxSubPath, observability-injector 消费)
   - RBAC RoleBinding (成员 → K8s 用户映射)

本模块 (platform-api workspace) 仅负责:
- 命名空间名规范化 (委托给 `aws_team_mapping.ensure_aws_ns_prefix`)
- NetworkPolicy spec 生成器骨架 (供 Phase 1 Operator 复用此纯函数)

ResourceQuota render 已不在本模块职责内 (HyperPod 自动出, 不需要我们生成).
任何 dict 渲染必须是无 IO 的纯函数, 避免和 orchestration 耦合.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.i18n import t
from app.modules.workspace.domain.aws_team_mapping import ensure_aws_ns_prefix

# K8s DNS-1123 Label (namespace 合法字符集): [a-z0-9]([-a-z0-9]*[a-z0-9])?
# AWS 额外限定首字母小写, 长度含前缀 hyperpod-ns- (12 字节) 后 ≤ 63
_K8S_NS_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
_K8S_NS_MAX_LEN = 63


def validate_namespace(ns: str) -> tuple[bool, str | None]:
    """校验 namespace 是否符合 K8s + AWS HyperPod 约束.

    Returns:
        (ok, error_message)
    """
    if not ns:
        return False, t("workspace.namespace_empty")
    if len(ns) > _K8S_NS_MAX_LEN:
        return False, t("workspace.namespace_too_long", length=len(ns), max=_K8S_NS_MAX_LEN)
    if not _K8S_NS_RE.match(ns):
        return False, t("workspace.namespace_pattern")
    return True, None


def normalize_namespace(user_input: str | None, default_from_name: str) -> str:
    """把用户输入规整成 `hyperpod-ns-<x>` 形式.

    - user_input None · 用 default_from_name (workspace.name)
    - 无论传啥都强制加 `hyperpod-ns-` 前缀 (幂等)

    与 AWS 自动建的 namespace 对齐, DevInstance 的 k8s_namespace 直接取此值。
    """
    raw = user_input or default_from_name
    return ensure_aws_ns_prefix(raw)


def build_namespace_manifest(
    namespace: str, *, workspace_name: str, labels: dict[str, str] | None = None
) -> dict[str, Any]:
    """构造 K8s Namespace manifest (预留接口 · Phase 1 才会用).

    当前 workspace 模块走 AWS CreateComputeQuota 路径, AWS 会自动建 ns;
    本函数仅在出现 **AWS 侧先失败后补救** 或 **CLI 直接建 ns 不建 quota**
    的场景下使用, 保持签名就位。
    """
    base_labels = {
        "hyperpod.amazonaws.com/managed-by": "platform-api",
        "hyperpod.amazonaws.com/team-name": workspace_name,
    }
    if labels:
        base_labels.update(labels)
    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {
            "name": namespace,
            "labels": base_labels,
        },
    }


def build_default_network_policy(namespace: str) -> dict[str, Any]:
    """默认 NetworkPolicy: deny-all ingress + egress allow-dns-only.

    决策固化: Phase 1 WorkspaceController (Go Operator) 在 reconcile
    HyperPod 自动建出的 namespace 时, 必须下发本函数返回的 NetworkPolicy
    (HyperPod team 不提供网络隔离, 这是多租户安全基线必需补足).

    本函数是纯函数 (无 IO), platform-api 不直接调用, 留作:
    - Phase 1 Go Operator 跨语言移植参照样板
    - admin 手工修复入口 (POST /admin/workspaces/{id}/repair-network)
    """
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": "default-deny-ingress",
            "namespace": namespace,
        },
        "spec": {
            "podSelector": {},
            "policyTypes": ["Ingress"],
        },
    }


def build_default_resource_quota(
    namespace: str, *, cpu: str = "0", memory: str = "0", gpu: str = "0"
) -> dict[str, Any]:
    """**已废弃**: 仅保留作为非 HyperPod 集群降级部署的兜底.

    决策固化: 当前路径 ResourceQuota 由 HyperPod team API
    (CreateComputeQuota) 自动产出, 本函数**不再被调用**.

    保留场景:
    - 非 HyperPod EKS 集群 (M3+ 多集群联邦时可能用到)
    - 管理员手工修复 (HyperPod 自动产出失败的边缘 case)
    """
    return {
        "apiVersion": "v1",
        "kind": "ResourceQuota",
        "metadata": {
            "name": "default-quota",
            "namespace": namespace,
        },
        "spec": {
            "hard": {
                "requests.cpu": cpu,
                "requests.memory": memory,
                "requests.nvidia.com/gpu": gpu,
            }
        },
    }
