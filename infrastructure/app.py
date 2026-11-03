#!/usr/bin/env python3
"""单 Stack 部署 (跨集群).

Stack 管全部: 平台层资源 (DDB/Cognito/IAM/ECR) + 平台 EKS 集群 (新建) +
平台集群 Pod Identity + 业务集群 access entry。

Stack 名 = {projectName}-platform-stack (带 project 前缀, 跟其它资源一致)。
跨集群 / 单集群由 cdk.json 的 platformClusterSuffix vs businessClusterName 决定。
"""
import aws_cdk as cdk

from stacks.log_archive_stack import LogArchiveStack
from stacks.platform_stack import PlatformStack

app = cdk.App()
account = app.node.try_get_context("account")
region = app.node.try_get_context("region")
project = app.node.try_get_context("projectName")

env = cdk.Environment(account=account, region=region)

PlatformStack(app, f"{project}-platform-stack", env=env)

# 日志备份 (独立 stack, 可单独 deploy/destroy): log group subscription → Firehose → S3
# 仅 logArchiveMode=cost|query 时创建 (与 deploy-platform.sh 一致); 留空不建,
# 避免 hyperpodClusterLogGroupName 未配时整个 app synth 失败。
if app.node.try_get_context("logArchiveMode") in ("cost", "query"):
    LogArchiveStack(app, f"{project}-log-archive-stack", env=env)

app.synth()
