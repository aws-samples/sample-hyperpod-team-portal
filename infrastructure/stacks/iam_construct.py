"""IAM 4 个 role:
  - platform-api-role        后端 Pod 执行 role (Pod Identity)
  - platform-pod-role        workspace-default SA (开发机 pod 共用) (Pod Identity)
  - ssm-managed-node-role    sidecar SSM 注册 (双 principal trust)
  - alb-controller-role      AWS Load Balancer Controller (Pod Identity)

权限从后端代码调用面推导 (设计 §5).
"""

import json
from pathlib import Path

from aws_cdk import aws_iam as iam
from constructs import Construct

POD_IDENTITY = iam.ServicePrincipal("pods.eks.amazonaws.com")
# 官方 ALB controller IAM policy (下载到 infrastructure/policies/)
_ALB_POLICY_JSON = Path(__file__).resolve().parents[1] / "policies" / "alb-controller-iam-policy.json"


def _add_pod_identity_trust(role: iam.Role) -> None:
    """Pod Identity 要 sts:AssumeRole + sts:TagSession 给 pods.eks principal."""
    role.assume_role_policy.add_statements(
        iam.PolicyStatement(
            actions=["sts:TagSession"],
            principals=[POD_IDENTITY],
        )
    )


class IamConstruct(Construct):
    def __init__(self, scope: Construct, cid: str, *,
                 project: str,
                 ddb_table_arns: list[str], amp_workspace_arn: str,
                 s3_bucket_names: list[str],
                 region: str, account: str,
                 business_cluster: str, platform_cluster: str,
                 idc_assume_role_arn: str = "") -> None:
        super().__init__(scope, cid)

        # EKS 集群 ARN (收窄 eks:* 的 resource, 防"给任意集群建 access entry 提权").
        # access-entry ARN 真实格式 (实测):
        #   arn:aws:eks:<r>:<a>:access-entry/<cluster>/role/<account>/<role>/<uuid>
        # CreateComputeQuota 内部建 entry 的 principal/uuid 动态, 故用 /* 通配, 但限定到业务集群。
        _biz_cluster_arn = (
            f"arn:aws:eks:{region}:{account}:cluster/{business_cluster}")
        _plat_cluster_arn = (
            f"arn:aws:eks:{region}:{account}:cluster/{platform_cluster}")
        _biz_access_entry_arn = (
            f"arn:aws:eks:{region}:{account}:access-entry/{business_cluster}/*")

        # cdk.json platformS3Buckets 解析出的桶 → ARN. 空列表 (没配桶) 则不授予任何
        # 桶的 object 权限 (不回退 * 通配, 避免放开账号内全部桶).
        # bucket 级 action (ListBucket) 用 _bucket_arns; object 级 (Get/PutObject) 用 _object_arns.
        _bucket_arns = [f"arn:aws:s3:::{b}" for b in s3_bucket_names]
        _object_arns = [f"arn:aws:s3:::{b}/*" for b in s3_bucket_names]

        # ---- platform-pod-role (workspace-default SA; 开发机 pod 共用) ----
        pod_role = iam.Role(
            self, "PlatformPodRole", role_name=f"{project}-platform-pod-role",
            assumed_by=POD_IDENTITY,
        )
        _add_pod_identity_trust(pod_role)
        # pod 内 aws s3 sync 拉数据集/推结果. 收窄到 cdk.json 配的桶 (没配桶则不授予).
        if s3_bucket_names:
            pod_role.add_to_policy(iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject"],
                resources=_object_arns))
            pod_role.add_to_policy(iam.PolicyStatement(
                actions=["s3:ListBucket"],
                resources=_bucket_arns))

        # ---- ssm-managed-node-role (sidecar SSM 注册; 双 principal) ----
        ssm_role = iam.Role(
            self, "SsmManagedNodeRole",
            role_name=f"{project}-sagemaker-space-SSMManagedNode",
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal("ssm.amazonaws.com"),
                iam.ServicePrincipal("sagemaker.amazonaws.com"),
            ),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSSMManagedInstanceCore"),
            ],
        )

        # ---- platform-api 执行 role (后端 Pod) ----
        api_role = iam.Role(
            self, "PlatformApiRole", role_name=f"{project}-platform-api-role",
            assumed_by=POD_IDENTITY,
        )
        _add_pod_identity_trust(api_role)
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query",
                     "dynamodb:UpdateItem", "dynamodb:DeleteItem",
                     "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem",
                     "dynamodb:Scan", "dynamodb:DescribeTable"],
            resources=ddb_table_arns))
        # ListTables 是账号级 action, resource 只能 * (healthz 启动检查用)
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["dynamodb:ListTables"],
            resources=["*"]))
        # 组1: resource 是 cluster ARN 的 action → 收窄到业务+平台两集群。
        # DescribeCluster / PodIdentity 关联 (api 给 workspace-default SA 关联 pod-role)。
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["eks:DescribeCluster",
                     "eks:CreatePodIdentityAssociation",
                     "eks:DeletePodIdentityAssociation",
                     "eks:ListPodIdentityAssociations"],
            resources=[_biz_cluster_arn, _plat_cluster_arn]))
        # 组2: access-entry 类 action (CreateComputeQuota 内部用调用者身份给业务集群
        # 建 access entry + 关联 HyperPod access policy; 否则 quota CreateFailed:
        # eks:AssociateAccessPolicy not authorized)。principal/uuid 动态 → access-entry/* 通配,
        # 但限定到【业务集群】, 堵住"给任意集群提权"。cluster ARN + access-entry ARN 双给
        # (AssociateAccessPolicy 等 resource 类型按 AWS 取其一, 双覆盖避免 not authorized)。
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["eks:CreateAccessEntry", "eks:DeleteAccessEntry",
                     "eks:DescribeAccessEntry", "eks:ListAccessEntries",
                     "eks:AssociateAccessPolicy", "eks:DisassociateAccessPolicy",
                     "eks:ListAssociatedAccessPolicies"],
            resources=[_biz_cluster_arn, _biz_access_entry_arn]))
        # 开发机 SSM 注册: CreateActivation 不支持资源级限定;
        # Deregister 收窄到混合激活的 mi-* (managed-instance), 不覆盖账号内 EC2。
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["ssm:CreateActivation", "ssm:DeleteActivation"],
            resources=["*"]))
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["ssm:DeregisterManagedInstance"],
            resources=[f"arn:aws:ssm:{region}:{account}:managed-instance/*"]))
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["fsx:DescribeFileSystems"], resources=["*"]))
        # ec2:DescribeInstanceTypes: 开发机调度判断 IG 是 CPU 还是 GPU
        # (按机型查 GpuInfo.Gpus[].Count, CPU 开发机软优先 CPU IG). 只读, 无资源约束.
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["ec2:DescribeInstanceTypes"], resources=["*"]))
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["ecr:DescribeRepositories", "ecr:ListImages",
                     "ecr:DescribeImages", "ecr:BatchGetImage",
                     "ecr:GetAuthorizationToken"],
            resources=["*"]))
        # s3:ListBucket 给 head_bucket 鉴权 (校验 bucket 存在/可达) 用.
        # 账号级 List/GetBucket* (扫候选桶 + 校验可达) 只能用 * resource.
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:ListAllMyBuckets", "s3:ListBucket",
                     "s3:GetBucketTagging", "s3:GetBucketLocation"],
            resources=["*"]))
        # object 级 Get/Put: 后端写训练/推理任务 YAML 归档 (_archive_cr_yaml).
        # 收窄到 cdk.json platformS3Buckets 配的桶 (没配桶则不授予).
        if s3_bucket_names:
            api_role.add_to_policy(iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject"],
                resources=_object_arns))
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["aps:QueryMetrics", "aps:GetSeries", "aps:GetLabels",
                     "aps:GetMetricMetadata"],
            resources=[amp_workspace_arn] if amp_workspace_arn else ["*"]))
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["sagemaker:ListComputeQuotas",
                     "sagemaker:DescribeComputeQuota",
                     "sagemaker:CreateComputeQuota",
                     "sagemaker:UpdateComputeQuota",
                     "sagemaker:DeleteComputeQuota",
                     "sagemaker:DescribeCluster",
                     "sagemaker:ListClusters",
                     # 节点列表/详情 (admin Nodes 页)
                     "sagemaker:ListClusterNodes",
                     "sagemaker:DescribeClusterNode",
                     # 优先级档 cluster policy (task governance): 读 + 增删改
                     # (优先级档管理页走 SageMaker scheduler config, 由官方 reconciler 建 WPC)
                     "sagemaker:ListClusterSchedulerConfigs",
                     "sagemaker:DescribeClusterSchedulerConfig",
                     "sagemaker:CreateClusterSchedulerConfig",
                     "sagemaker:UpdateClusterSchedulerConfig",
                     "sagemaker:DeleteClusterSchedulerConfig"],
            resources=["*"]))
        # IdC 查用户 (admin 加成员). 两种部署形态:
        #   - 同账号: IdC 在本账号 → 直接给 identitystore 只读 (resource 只能 *).
        #   - 跨账号: IdC 在 org 管理账号 → 给 sts:AssumeRole + sts:TagSession 到管理账号
        #     那个只读角色 (identitystore 权限挂在对方角色上, 见 docs). 收窄到该 ARN。
        #     TagSession 必需: EKS Pod Identity 的会话自带 session tag, 再 assume 跨账号
        #     role 时被要求 sts:TagSession, 缺了报 AccessDenied on sts:TagSession。
        if idc_assume_role_arn:
            api_role.add_to_policy(iam.PolicyStatement(
                actions=["sts:AssumeRole", "sts:TagSession"],
                resources=[idc_assume_role_arn]))
        else:
            api_role.add_to_policy(iam.PolicyStatement(
                actions=["identitystore:GetUserId", "identitystore:DescribeUser",
                         "identitystore:ListUsers"],
                resources=["*"]))
        # CloudWatch Logs (日志查看: Insights 查询 + 拉日志流/事件)
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["logs:StartQuery", "logs:GetQueryResults",
                     "logs:GetLogEvents", "logs:FilterLogEvents",
                     "logs:DescribeLogGroups", "logs:DescribeLogStreams"],
            resources=["*"]))
        # CloudWatch 指标 (FSx 存储监控: GetMetricData/ListMetrics).
        # metric API 不支持 resource 级限定, 用 *。
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["cloudwatch:GetMetricData", "cloudwatch:ListMetrics"],
            resources=["*"]))
        # PassRole: 把 pod/ssm role 交给 EKS Pod Identity / SSM。
        # GetRole: CreatePodIdentityAssociation 内部校验目标 role 存在时要 iam:GetRole。
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["iam:PassRole", "iam:GetRole"],
            resources=[pod_role.role_arn, ssm_role.role_arn]))

        # ---- 镜像在线构建 (CodeBuild) ----
        # 触发构建 + 查状态; 传 context 到 S3 source 桶; PassRole 给 CodeBuild
        # service role; 幂等建 ws ECR repo (logs:GetLogEvents 已在上方 logs 组内)。
        _cb_project_arn = f"arn:aws:codebuild:{region}:{account}:project/{project}-image-builder"
        _cb_role_arn = f"arn:aws:iam::{account}:role/{project}-codebuild-image-builder"
        _src_bucket_arn = f"arn:aws:s3:::{project}-image-build-src-{account}/*"
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["codebuild:StartBuild", "codebuild:BatchGetBuilds"],
            resources=[_cb_project_arn]))
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:PutObject"], resources=[_src_bucket_arn]))
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["iam:PassRole"], resources=[_cb_role_arn]))
        api_role.add_to_policy(iam.PolicyStatement(
            actions=["ecr:CreateRepository", "ecr:PutLifecyclePolicy",
                     "ecr:DescribeRepositories"],
            resources=["*"]))

        # ---- ALB controller role ----
        alb_role = iam.Role(
            self, "AlbControllerRole",
            role_name=f"{project}-aws-load-balancer-controller",
            assumed_by=POD_IDENTITY,
        )
        _add_pod_identity_trust(alb_role)
        # 用官方完整 IAM policy. 来源 kubernetes-sigs/aws-load-balancer-controller
        # main 分支 (匹配 controller v3.4.0, 含 DescribeListenerAttributes 等新 action).
        # ⚠️ 换 controller 版本时, 同步更新 policies/alb-controller-iam-policy.json 到对应版本.
        alb_policy_doc = json.loads(_ALB_POLICY_JSON.read_text())
        for i, stmt in enumerate(alb_policy_doc["Statement"]):
            alb_role.add_to_policy(iam.PolicyStatement.from_json(stmt))

        self.platform_pod_role_arn = pod_role.role_arn
        self.ssm_managed_node_role_arn = ssm_role.role_arn
        self.platform_api_role_arn = api_role.role_arn
        self.platform_api_role = api_role
        self.alb_controller_role_arn = alb_role.role_arn
