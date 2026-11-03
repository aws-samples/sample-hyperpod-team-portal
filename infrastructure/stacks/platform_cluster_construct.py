"""平台 EKS 集群 (CDK 新建, L1 CfnCluster).

跨集群部署: 平台前后端 + worker 跑在这个独立集群, 远程操作业务集群
(hp-fsx-demo) 的开发机/FSx。设计见
docs/deployment-guideline.md (跨集群架构)

要点:
- 与业务集群同 VPC (podIP 互通, 开发机网页代理直达, 无需 peering)
- 纯净小集群: 只跑平台 pod, 不要 HyperPod/GPU
- authenticationMode=API_AND_CONFIG_MAP → 支持 access entry (后端 role 进业务集群
  靠业务集群的 access entry; 本集群也用 API 模式便于管理)
- 全 L1 (Cfn*), 跟现有 construct 一致
"""

from aws_cdk import aws_eks as eks
from aws_cdk import aws_iam as iam
from constructs import Construct

from stacks.nodegroup_construct import NodegroupConstruct


class PlatformClusterConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        cluster_name: str,
        k8s_version: str,
        subnet_ids: list[str],
    ) -> None:
        super().__init__(scope, cid)

        # ---- EKS 控制面 IAM role ----
        cluster_role = iam.Role(
            self, "PlatformClusterRole",
            assumed_by=iam.ServicePrincipal("eks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonEKSClusterPolicy"),
            ],
        )

        # ---- EKS 集群本身 ----
        self.cluster = eks.CfnCluster(
            self, "PlatformCluster",
            name=cluster_name,
            version=k8s_version,
            role_arn=cluster_role.role_arn,
            resources_vpc_config=eks.CfnCluster.ResourcesVpcConfigProperty(
                subnet_ids=subnet_ids,
                # 平台集群 endpoint: private-only (不暴露公网, 攻击面小)。
                # ⚠️ 运维 (kubectl/helm/cluster-init) 必须在 VPC 内做 (EC2 部署机 / VPN / 跳板);
                #    local 直连失效。EC2 走 private 需放行其 SG → 集群 SG 443
                #    (cluster-init.sh 的 access 步骤已自动放行)。
                endpoint_private_access=True,
                endpoint_public_access=False,
            ),
            # API_AND_CONFIG_MAP: 启用 access entry 机制 (跨集群授权一致用 access entry)
            access_config=eks.CfnCluster.AccessConfigProperty(
                authentication_mode="API_AND_CONFIG_MAP",
                bootstrap_cluster_creator_admin_permissions=True,
            ),
        )
        self.cluster_name = cluster_name

        # ---- addon: 集群基础组件 ----
        # vpc-cni / coredns / kube-proxy: 集群网络/DNS 基础
        # eks-pod-identity-agent: 平台 pod 用 Pod Identity 拿 AWS 凭据必需
        for addon in (
            "vpc-cni",
            "coredns",
            "kube-proxy",
            "eks-pod-identity-agent",
        ):
            a = eks.CfnAddon(
                self, f"Addon-{addon}",
                addon_name=addon,
                cluster_name=cluster_name,
                resolve_conflicts="OVERWRITE",
            )
            a.add_dependency(self.cluster)

        # ---- CPU node group (复用现有 construct) ----
        ng = NodegroupConstruct(
            self, "NodeGroup",
            cluster_name=cluster_name,
            subnet_ids=subnet_ids,
        )
        ng.nodegroup.add_dependency(self.cluster)
        self.node_role = ng.node_role
