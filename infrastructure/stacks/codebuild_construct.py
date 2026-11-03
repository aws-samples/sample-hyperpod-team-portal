"""镜像在线构建 CodeBuild project + S3 source 桶 + service role。

用户提交 Dockerfile → 后端生成 buildspec 打包传 S3 → StartBuild(privileged 跑
docker build) → push 到 ECR repo (名 = 用户输入的 namespace/repo-name, 平台不加
前缀)。service role 的 ECR push scope 放开到自账号任意 repo (repository/*)。
"""

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from constructs import Construct


class ImageBuildConstruct(Construct):
    def __init__(
        self, scope: Construct, cid: str, *, project: str, account: str, region: str
    ) -> None:
        super().__init__(scope, cid)

        bucket = s3.Bucket(
            self,
            "SourceBucket",
            bucket_name=f"{project}-image-build-src-{account}",
            removal_policy=RemovalPolicy.RETAIN,
            # context zip 一次性用, 7 天后自动清
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(7))],
        )

        role = iam.Role(
            self,
            "CodeBuildRole",
            role_name=f"{project}-codebuild-image-builder",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[f"arn:aws:logs:{region}:{account}:log-group:/aws/codebuild/*"],
            )
        )
        bucket.grant_read(role)
        role.add_to_policy(
            iam.PolicyStatement(actions=["ecr:GetAuthorizationToken"], resources=["*"])
        )
        # push: repo 名由用户自定 (namespace/repo-name, 平台不加前缀), 故 scope 放开到
        # 自账号任意 repo。该 role 仅镜像构建用 + 仅后端触发, 攻击面可控。
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage", "ecr:PutImage", "ecr:InitiateLayerUpload",
                    "ecr:UploadLayerPart", "ecr:CompleteLayerUpload",
                ],
                resources=[f"arn:aws:ecr:{region}:{account}:repository/*"],
            )
        )
        # 显式拒绝推平台自身镜像仓库 (ecr_construct 的 {project}-platform-api/-worker/
        # frontend), 防用户 Dockerfile 借构建 role 覆盖平台镜像。
        role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.DENY,
                actions=[
                    "ecr:PutImage", "ecr:InitiateLayerUpload",
                    "ecr:UploadLayerPart", "ecr:CompleteLayerUpload",
                ],
                resources=[
                    f"arn:aws:ecr:{region}:{account}:repository/{project}-{name}"
                    for name in ("platform-api", "platform-worker", "frontend")
                ],
            )
        )
        # pull: 放开到 * (用户 Dockerfile FROM 任意官方/公共镜像 DLC/SageMaker 等;
        # 实际可拉性由对方 repo 的 resource policy 决定, IAM 侧不主动挡)。
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                ],
                resources=["*"],
            )
        )

        codebuild.CfnProject(
            self,
            "Project",
            name=f"{project}-image-builder",
            service_role=role.role_arn,
            source=codebuild.CfnProject.SourceProperty(
                type="S3",
                location=f"{bucket.bucket_name}/placeholder.zip",
                build_spec="buildspec.yml",
            ),
            artifacts=codebuild.CfnProject.ArtifactsProperty(type="NO_ARTIFACTS"),
            environment=codebuild.CfnProject.EnvironmentProperty(
                type="LINUX_CONTAINER",
                image="aws/codebuild/amazonlinux2-x86_64-standard:5.0",
                compute_type="BUILD_GENERAL1_LARGE",  # 默认; StartBuild 时按用户选覆盖
                privileged_mode=True,  # docker build 必须
            ),
            timeout_in_minutes=120,
        )

        self.project_name = f"{project}-image-builder"
        self.bucket_name = bucket.bucket_name
        self.service_role_arn = role.role_arn
