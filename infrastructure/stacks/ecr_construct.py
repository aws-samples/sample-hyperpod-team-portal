"""ECR repositories: platform-api + platform-worker + frontend 镜像仓库.

名字带 projectName 前缀, 跟其他资源统一. RETAIN — cdk destroy 不删镜像.
"""

from aws_cdk import RemovalPolicy
from aws_cdk import aws_ecr as ecr
from constructs import Construct


class EcrConstruct(Construct):
    def __init__(self, scope: Construct, cid: str, *, project: str) -> None:
        super().__init__(scope, cid)

        def repo(name: str) -> ecr.Repository:
            return ecr.Repository(
                self, name,
                repository_name=f"{project}-{name.lower()}",
                removal_policy=RemovalPolicy.RETAIN,  # 删 stack 不删镜像
                empty_on_delete=False,
                image_scan_on_push=True,
            )

        self.api_repo = repo("platform-api")
        self.worker_repo = repo("platform-worker")
        self.frontend_repo = repo("frontend")
        self.api_repo_uri = self.api_repo.repository_uri
        self.worker_repo_uri = self.worker_repo.repository_uri
        self.frontend_repo_uri = self.frontend_repo.repository_uri
