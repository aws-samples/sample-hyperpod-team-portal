"""EKS Pod Identity associations + access entry (跨集群拆分).

跨集群部署后拆成两块, 分属两个集群:
  - PlatformPodIdentityConstruct: 平台 pod 的 Pod Identity (AWS 权限),
    建在**平台集群** (pod 所在地)。
  - BusinessAccessEntryConstruct: 平台 role 映射成业务集群 K8s 用户 (带
    cluster-workspace-admin group + ClusterAdmin policy), 建在**业务集群**
    (让后端能远程操作业务集群 CR/PV/exec)。

单集群部署时两者都指同一个 cluster_name 即可 (退化兼容)。

全用 L1 (Cfn*), 不依赖 import 完整 EKS 集群对象。
设计: docs/deployment-guideline.md (跨集群架构)
"""

from aws_cdk import aws_eks as eks
from constructs import Construct

_CLUSTER_ADMIN_POLICY = (
    "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
)


class PlatformPodIdentityConstruct(Construct):
    """平台集群: platform-api SA + ALB controller SA 的 Pod Identity."""

    def __init__(self, scope: Construct, cid: str, *,
                 cluster_name: str, platform_ns: str,
                 api_role_arn: str, alb_role_arn: str) -> None:
        super().__init__(scope, cid)

        # platform-api SA → api role (AWS 权限)
        eks.CfnPodIdentityAssociation(
            self, "ApiPodIdentity",
            cluster_name=cluster_name,
            namespace=platform_ns,
            service_account="platform-api",
            role_arn=api_role_arn)

        # ALB controller SA → alb role
        eks.CfnPodIdentityAssociation(
            self, "AlbPodIdentity",
            cluster_name=cluster_name,
            namespace="kube-system",
            service_account="aws-load-balancer-controller",
            role_arn=alb_role_arn)


class BusinessAccessEntryConstruct(Construct):
    """业务集群: 平台 role 的 access entry (远程操作业务集群 K8s 的授权).

    收紧方案 (2026-06-24): access entry **不挂 AmazonEKSClusterAdminPolicy**,
    只做 kubernetesGroups 映射 (→ cluster-workspace-admin)。真正权限由业务集群上
    apply 的 ClusterRole/ClusterRoleBinding 决定 (deploy/k8s/business-cluster-rbac.yaml,
    最小权限 = api 调用面 + workspace-developer 提权保护)。

    ⚠️ 部署顺序: 必须在后端 pod 操作业务集群之前, 把 business-cluster-rbac.yaml apply 到
    业务集群; 否则 api 操作 → 403 (有 group 身份但 group 没绑任何 ClusterRole)。

    worker 复用 api role/group (worker_role_arn=None), 跟随同一 group → 同一 ClusterRole。
    """

    def __init__(self, scope: Construct, cid: str, *,
                 cluster_name: str,
                 api_role_arn: str,
                 worker_role_arn: str | None,
                 workspace_admin_group: str) -> None:
        super().__init__(scope, cid)

        # 只映射 group, 不挂 access policy (权限走业务集群 ClusterRole)。
        eks.CfnAccessEntry(
            self, "ApiAccessEntry",
            cluster_name=cluster_name,
            principal_arn=api_role_arn,
            kubernetes_groups=[workspace_admin_group],
            type="STANDARD")

        if worker_role_arn:
            eks.CfnAccessEntry(
                self, "WorkerAccessEntry",
                cluster_name=cluster_name,
                principal_arn=worker_role_arn,
                kubernetes_groups=[workspace_admin_group],
                type="STANDARD")
