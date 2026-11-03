"""单 Stack (跨集群): 平台集群 + 平台层资源 + 双集群接入.

设计: docs/deployment-guideline.md (跨集群架构)

一个 HyperPodPlatformStack 管全部:
  - 平台层资源 (DDB/Cognito/IAM/ECR) —— 跟集群无关
  - 平台 EKS 集群 (CDK 新建, 同业务 VPC) + CPU node group + addon
  - 平台集群 Pod Identity (platform-api / ALB controller SA → role)
  - 业务集群 access entry (让平台 role 远程操作业务集群 hp-fsx-demo)

跨集群: platformClusterName != businessClusterName。
单集群退化: 两者填同名 → node group/Pod Identity/access entry 都落同一集群。

CDK 只管 AWS 资源; K8s 侧 (前后端 Deployment + Ingress) 走 manifest。
"""

from aws_cdk import CfnOutput, Stack, Tags
from constructs import Construct

from stacks.codebuild_construct import ImageBuildConstruct
from stacks.cognito_construct import CognitoConstruct
from stacks.ddb_construct import DdbConstruct
from stacks.ecr_construct import EcrConstruct
from stacks.eks_access_construct import (
    BusinessAccessEntryConstruct,
    PlatformPodIdentityConstruct,
)
from stacks.iam_construct import IamConstruct
from stacks.platform_cluster_construct import PlatformClusterConstruct


class PlatformStack(Stack):
    def __init__(self, scope: Construct, cid: str, **kwargs) -> None:
        super().__init__(scope, cid, **kwargs)
        ctx = self.node.try_get_context

        project = ctx("projectName")
        region = ctx("region")
        # 平台集群名 = {project}-{suffix}, 跟 DDB/ECR 一样带 project 前缀.
        platform_cluster = f"{project}-{ctx('platformClusterSuffix') or 'platform'}"
        business_cluster = ctx("businessClusterName")
        platform_ns = ctx("platformNamespace")
        amp_id = ctx("ampWorkspaceId") or ""
        amp_arn = (
            f"arn:aws:aps:{region}:{self.account}:workspace/{amp_id}"
            if amp_id else ""
        )
        # platformS3Buckets 格式 bucket[:region[:友好名]], 逗号分隔. 只取桶名,
        # 用来把 IAM S3 权限收窄到这些桶 (api_role 写 YAML 归档 + pod_role pod 内 s3 sync).
        s3_bucket_names = [
            item.split(":")[0].strip()
            for item in (ctx("platformS3Buckets") or "").split(",")
            if item.strip()
        ]

        Tags.of(self).add("Project", project)
        Tags.of(self).add("ManagedBy", "cdk")

        # bootstrapAdmins: 逗号分隔的初始超管 username (= IdC SAML token 的
        # identities[0].userId)。部署时写入 PlatformAdmins 表, 解决"无 API 建首个超管"。
        bootstrap_admins = [
            u.strip()
            for u in (ctx("bootstrapAdmins") or "").split(",")
            if u.strip()
        ]

        # ---- 平台层资源 (不绑集群, 已存在则 CFN update 不报错) ----
        ddb = DdbConstruct(
            self, "Ddb", prefix=project, bootstrap_admins=bootstrap_admins,
        )
        CfnOutput(self, "DdbTablePrefix", value=project)

        ecr_c = EcrConstruct(self, "Ecr", project=project)
        CfnOutput(self, "ApiRepoUri", value=ecr_c.api_repo_uri)
        CfnOutput(self, "WorkerRepoUri", value=ecr_c.worker_repo_uri)
        CfnOutput(self, "FrontendRepoUri", value=ecr_c.frontend_repo_uri)

        # 镜像在线构建 (CodeBuild): project 名 + source 桶输出给 render-and-apply
        # 注入后端 env (CODEBUILD_PROJECT_NAME / IMAGE_BUILD_SOURCE_BUCKET)。
        image_build = ImageBuildConstruct(
            self, "ImageBuild", project=project, account=self.account, region=region)
        CfnOutput(self, "CodeBuildProjectName", value=image_build.project_name)
        CfnOutput(self, "ImageBuildSourceBucket", value=image_build.bucket_name)

        cognito = CognitoConstruct(
            # domain_prefix 加 -v2: 配合 UserPoolV2 重建, 避开旧池 domain 删除延迟导致的
            # "domain already exists" 撞名 (Cognito 删 domain 有几分钟延迟)。
            self, "Cognito", domain_prefix=f"{project}-{self.account}-v2",
            # callback/logout 从 albDomainName 拼 (deploy 即对, 免事后回填 callback)
            alb_domain=ctx("albDomainName") or "")
        CfnOutput(self, "CognitoUserPoolId", value=cognito.user_pool_id)
        CfnOutput(self, "CognitoClientId", value=cognito.client_id)
        CfnOutput(self, "CognitoDomain", value=cognito.domain)

        iam_c = IamConstruct(
            self, "Iam",
            project=project,
            ddb_table_arns=ddb.table_arns,
            amp_workspace_arn=amp_arn,
            s3_bucket_names=s3_bucket_names,
            region=region, account=self.account,
            business_cluster=business_cluster,
            platform_cluster=platform_cluster,
            idc_assume_role_arn=ctx("idcAssumeRoleArn") or "")
        CfnOutput(self, "PlatformApiRoleArn", value=iam_c.platform_api_role_arn)
        CfnOutput(self, "PlatformPodRoleArn", value=iam_c.platform_pod_role_arn)
        CfnOutput(self, "SsmManagedNodeRoleArn",
                  value=iam_c.ssm_managed_node_role_arn)
        CfnOutput(self, "AlbControllerRoleArn",
                  value=iam_c.alb_controller_role_arn)

        # ---- 平台 EKS 集群 (CDK 新建, 同业务 VPC) + node group + addon ----
        cluster = PlatformClusterConstruct(
            self, "PlatformCluster",
            cluster_name=platform_cluster,
            k8s_version=ctx("platformK8sVersion") or "1.36",
            subnet_ids=ctx("privateSubnetIds"),
        )
        CfnOutput(self, "PlatformClusterName", value=cluster.cluster_name)

        # ---- Pod Identity (指平台集群; pod 在那拿 AWS 凭据) ----
        pod_id = PlatformPodIdentityConstruct(
            self, "PodIdentity",
            cluster_name=platform_cluster,
            platform_ns=platform_ns,
            api_role_arn=iam_c.platform_api_role_arn,
            alb_role_arn=iam_c.alb_controller_role_arn)
        pod_id.node.add_dependency(cluster)  # 集群先建好才能关联 SA

        # ---- 业务集群 access entry (让平台 role 远程操作业务集群) ----
        # 跨集群时 cluster_name = 业务集群; 单集群退化时 = 同一集群。
        BusinessAccessEntryConstruct(
            self, "BusinessAccess",
            cluster_name=business_cluster,
            api_role_arn=iam_c.platform_api_role_arn,
            worker_role_arn=None,  # worker 复用 api role
            workspace_admin_group=ctx("clusterWorkspaceAdminGroup"))

        # ---- 开发机 directSSH ----
        # directSSH 全套 (Route53 私有 zone + external-dns role/policy + external-dns
        # addon + spaces directSSH 配置) 都在 deploy/cluster-prereq.sh 里建: 它跑在
        # cdk deploy 之前, 而 external-dns addon 依赖 role, role policy 依赖 zone ARN,
        # 三者必须先于 CDK 建, 故不放 CDK。见 cluster-prereq.sh step_externaldns/step_spaces。
        # 节点 SG 22222 由 deploy/cross-cluster-sg.sh 放通。
