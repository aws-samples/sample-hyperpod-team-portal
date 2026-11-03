"""EKS CPU managed node group (给平台组件用, 跟 GPU 训练隔离).

用 L1 CfnNodegroup 避开 import HyperPod 底层 EKS 完整对象的坑.
节点不带 hyperpod label, 不会被 Kueue flavor 匹配 → 不抢 GPU 也不被 GPU 调度抢.
"""

from aws_cdk import aws_eks as eks
from aws_cdk import aws_iam as iam
from constructs import Construct


class NodegroupConstruct(Construct):
    def __init__(self, scope: Construct, cid: str, *,
                 cluster_name: str, subnet_ids: list[str]) -> None:
        super().__init__(scope, cid)

        node_role = iam.Role(
            self, "PlatformNodeRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonEKSWorkerNodePolicy"),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonEKS_CNI_Policy"),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonEC2ContainerRegistryReadOnly"),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSSMManagedInstanceCore"),
            ],
        )

        self.nodegroup = eks.CfnNodegroup(
            self, "PlatformCpuNodegroup",
            cluster_name=cluster_name,
            node_role=node_role.role_arn,
            subnets=subnet_ids,  # 必须私有 subnet
            nodegroup_name="platform-cpu",
            instance_types=["m5.2xlarge"],
            scaling_config=eks.CfnNodegroup.ScalingConfigProperty(
                min_size=2, max_size=2, desired_size=2),
            labels={"role": "platform"},
            ami_type="AL2023_x86_64_STANDARD",
        )
        self.node_role = node_role
