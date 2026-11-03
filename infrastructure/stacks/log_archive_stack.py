"""独立 Stack: 日志备份到 S3 (log group subscription → Firehose → S3).

与 PlatformStack 解耦, 可单独 deploy/destroy:
  cdk deploy hpd-plat-log-archive-stack

模式由 cdk.json 的 logArchiveMode 切换 (cost | query), 见 LogArchiveConstruct。
"""

from aws_cdk import CfnOutput, Stack, Tags
from constructs import Construct

from stacks.log_archive_construct import LogArchiveConstruct


class LogArchiveStack(Stack):
    def __init__(self, scope: Construct, cid: str, **kwargs) -> None:
        super().__init__(scope, cid, **kwargs)
        ctx = self.node.try_get_context

        project = ctx("projectName")
        region = ctx("region")
        log_group_name = ctx("hyperpodClusterLogGroupName")
        mode = ctx("logArchiveMode") or "cost"

        if not log_group_name:
            raise ValueError(
                "cdk.json 缺 hyperpodClusterLogGroupName (要备份的 log group 名)"
            )

        Tags.of(self).add("Project", project)
        Tags.of(self).add("ManagedBy", "cdk")
        Tags.of(self).add("Component", "log-archive")

        archive = LogArchiveConstruct(
            self,
            "LogArchive",
            project=project,
            account=self.account,
            region=region,
            log_group_name=log_group_name,
            mode=mode,
        )

        CfnOutput(self, "LogArchiveBucketName", value=archive.bucket_name)
        CfnOutput(self, "LogArchiveStreamName", value=archive.stream_name)
        CfnOutput(self, "LogArchiveMode", value=archive.mode)
