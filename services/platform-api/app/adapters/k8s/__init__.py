"""adapters/k8s · Kubernetes 异步客户端 (按 CR kind 分文件).

入口:
    ``K8sClient``: 聚合所有 kind mixin 的公共类, 签名与旧 ``app.services.k8s_client.K8sClient`` 完全一致.
    ``K8sAPIError``: 统一异常类型.
    ``_to_primitive``: 保留给 kueue_client 等已有下游使用 (私有, 不建议新代码引用).

模块拆分:
    - base.py                  K8sClientBase + _to_primitive
    - errors.py                K8sAPIError
    - node.py                  core/v1 Node 只读
    - workspace.py             workspace.jupyter.org/v1alpha1 Workspace CRUD
    - workspace_template.py 同上 WorkspaceTemplate CRUD
    - workspace_connection.py  connection.workspace.jupyter.org/v1alpha1 (aggregated API)
    - pvc.py                   core/v1 PersistentVolumeClaim 只读
    - secret.py core/v1 Secret · GitHub token 托管
    - pod.py                   core/v1 Pod 查询 + exec + cat 文件
    - hpj.py                   sagemaker.amazonaws.com/v1 HyperPodPyTorchJob CRUD
    - inference.py             inference.sagemaker.aws.amazon.com/v1 InferenceEndpointConfig CRUD
    - job.py                   batch/v1 Job CRUD + 按 job-name 列 Pod
    - workload.py              kueue.x-k8s.io/v1beta1 Workload 只读 (按 job-uid 列)
    - topology.py              kueue ResourceFlavor(v1beta1) / Topology(v1alpha1) 只读, 均 cluster-scoped

向后兼容:
    旧 import path ``from app.services.k8s_client import K8sClient, K8sAPIError`` 仍有效
    (app/services/k8s_client.py 为 thin re-export shim).
"""

from __future__ import annotations

from .base import K8sClientBase, _to_primitive
from .errors import K8sAPIError
from .configmap import ConfigMapMixin
from .dynamo import DynamoMixin
from .hpj import HpjMixin
from .inference import InferenceMixin
from .ingress import IngressMixin
from .job import JobMixin
from .node import NodeMixin
from .pod import PodMixin
from .priority import PriorityMixin
from .pvc import PvcMixin
from .rayjob import RayJobMixin
from .llmd import LlmdMixin
from .secret import SecretMixin
from .topology import TopologyMixin
from .workspace import WorkspaceMixin
from .workspace_connection import WorkspaceConnectionMixin
from .workload import WorkloadMixin
from .workspace_resources import WorkspaceResourcesMixin
from .workspace_template import WorkspaceTemplateMixin


class K8sClient(
    NodeMixin,
    WorkspaceMixin,
    WorkspaceTemplateMixin,
    WorkspaceConnectionMixin,
    WorkspaceResourcesMixin,
    PvcMixin,
    SecretMixin,
    PodMixin,
    HpjMixin,
    InferenceMixin,
    IngressMixin,
    DynamoMixin,
    RayJobMixin,
    LlmdMixin,
    ConfigMapMixin,
    JobMixin,
    WorkloadMixin,
    PriorityMixin,
    TopologyMixin,
    K8sClientBase,
):
    """Kubernetes 异步客户端 · 聚合所有 CR kind mixin.

    用法与旧 K8sClient 完全一致::

        client = K8sClient(context="hypd-dev-cluster")
        nodes = await client.list_nodes()
        ws = await client.get_workspace("team-a", "foo")
    """


__all__ = [
    "K8sAPIError",
    "K8sClient",
    "K8sClientBase",
    "_to_primitive",
]
