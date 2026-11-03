"""日志备份到 S3: CloudWatch log group subscription filter → Firehose → S3.

备份 hyperpodClusterLogGroupName 指向的 log group 的日志到专属 S3 桶。

两种模式 (cdk.json 的 logArchiveMode 切换):
  - cost:  不解压。CloudWatch 发来的已是 gzip, Firehose 原样落盘 (多-member .gz)。
           省存储, 适合偶尔查 (查前需 Glue ETL 转 Parquet)。
  - query: Firehose 开 Decompression + CloudWatch message extraction, 落地一行一条明文,
           Athena 直查。代价: S3 体积增大 (解压后)。

资源:
  - S3 桶 (专用, RETAIN)
  - Firehose delivery stream (Extended S3 destination)
  - CloudWatch Logs subscription filter (引用现有 log group, 不新建)
  - 两个最小权限 IAM role:
      * Firehose role: 只能写本桶 + 写自身 CW 错误日志
      * subscription filter role: 只能 PutRecord* 到本流 (带 SourceArn 防 confused deputy)

"""

from aws_cdk import RemovalPolicy
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kinesisfirehose as firehose
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from constructs import Construct

_FH = firehose.CfnDeliveryStream


class LogArchiveConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        project: str,
        account: str,
        region: str,
        log_group_name: str,
        mode: str = "cost",
    ) -> None:
        super().__init__(scope, cid)

        if mode not in ("cost", "query"):
            raise ValueError(f"logArchiveMode 必须是 cost 或 query, 得到: {mode}")

        # ---- S3 备份桶 ({project}-log-archive-{account}-{region}) ----
        bucket = s3.Bucket(
            self,
            "ArchiveBucket",
            bucket_name=f"{project}-log-archive-{account}-{region}",
            removal_policy=RemovalPolicy.RETAIN,  # 删 stack 不删日志
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
        )

        # ---- Firehose 用的 IAM role (最小权限: 只写本桶 + 自身错误日志) ----
        fh_role = iam.Role(
            self,
            "FirehoseRole",
            role_name=f"{project}-log-archive-firehose",
            assumed_by=iam.ServicePrincipal("firehose.amazonaws.com"),
        )
        bucket.grant_read_write(fh_role)  # Firehose 写对象 + multipart 需要读桶元数据
        # Firehose 把自身投递错误写到一个专用 log group (下方 create), 收窄到该组
        fh_error_log_group = logs.LogGroup(
            self,
            "FirehoseErrorLogGroup",
            log_group_name=f"/aws/kinesisfirehose/{project}-log-archive",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )
        fh_role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:PutLogEvents"],
                resources=[fh_error_log_group.log_group_arn + ":*"],
            )
        )

        # ---- S3 落盘前缀 + processing (两模式差异只在这) ----
        # 两种模式都按 dt=/hour= 分区, 查询时可分区裁剪。
        common_partition = "dt=!{timestamp:yyyy-MM-dd}/hour=!{timestamp:HH}/"
        if mode == "query":
            prefix = f"decompressed/{common_partition}"
            # Decompression 解 gzip + CloudWatchLogProcessing 剥信封只留 message
            processing = _FH.ProcessingConfigurationProperty(
                enabled=True,
                processors=[
                    _FH.ProcessorProperty(type="Decompression"),
                    _FH.ProcessorProperty(
                        type="CloudWatchLogProcessing",
                        parameters=[
                            _FH.ProcessorParameterProperty(
                                parameter_name="DataMessageExtraction",
                                parameter_value="true",
                            )
                        ],
                    ),
                ],
            )
        else:  # cost
            prefix = f"raw/{common_partition}"
            processing = _FH.ProcessingConfigurationProperty(enabled=False)

        # error_output_prefix 必须含 !{firehose:error-output-type} (Firehose 硬性要求),
        # 它区分 processing-failed / 各类 delivery-failed 子目录。
        error_prefix = (
            "errors/!{firehose:error-output-type}/dt=!{timestamp:yyyy-MM-dd}/"
        )

        stream = firehose.CfnDeliveryStream(
            self,
            "DeliveryStream",
            delivery_stream_name=f"{project}-log-archive",
            delivery_stream_type="DirectPut",
            extended_s3_destination_configuration=_FH.ExtendedS3DestinationConfigurationProperty(
                bucket_arn=bucket.bucket_arn,
                role_arn=fh_role.role_arn,
                prefix=prefix,
                error_output_prefix=error_prefix,
                # 攒 5MB 或 300s flush 一次 (归档准实时够用)
                buffering_hints=_FH.BufferingHintsProperty(
                    interval_in_seconds=300, size_in_m_bs=5
                ),
                # 落盘再压一层 gzip (query 模式解压后落盘, 加 gzip 省存储;
                # cost 模式源已是 gzip, 这里 UNCOMPRESSED 避免双重压缩)
                compression_format="GZIP" if mode == "query" else "UNCOMPRESSED",
                processing_configuration=processing,
                cloud_watch_logging_options=_FH.CloudWatchLoggingOptionsProperty(
                    enabled=True,
                    log_group_name=fh_error_log_group.log_group_name,
                    log_stream_name="S3Delivery",
                ),
            ),
        )
        stream.node.add_dependency(fh_role)

        # ---- subscription filter 用的 IAM role (最小权限 + 防 confused deputy) ----
        sub_role = iam.Role(
            self,
            "SubscriptionRole",
            role_name=f"{project}-log-archive-subscription",
            assumed_by=iam.ServicePrincipal(
                "logs.amazonaws.com",
                conditions={
                    # 只允许本账号本 region 的 log group 触发, 防 confused deputy
                    "StringLike": {
                        "aws:SourceArn": f"arn:aws:logs:{region}:{account}:*"
                    }
                },
            ),
        )
        sub_role.add_to_policy(
            iam.PolicyStatement(
                actions=["firehose:PutRecord", "firehose:PutRecordBatch"],
                resources=[stream.attr_arn],
            )
        )

        # ---- subscription filter (引用现有 log group, 不新建) ----
        # 用 L1 CfnSubscriptionFilter 以引用 by-name 的既有 log group。
        # filter_pattern="" = 全部日志归档。
        sub_filter = logs.CfnSubscriptionFilter(
            self,
            "SubscriptionFilter",
            log_group_name=log_group_name,
            filter_pattern="",
            destination_arn=stream.attr_arn,
            role_arn=sub_role.role_arn,
        )
        sub_filter.node.add_dependency(stream)
        sub_filter.node.add_dependency(sub_role)

        # 对外暴露
        self.bucket_name = bucket.bucket_name
        self.bucket_arn = bucket.bucket_arn
        self.stream_name = stream.delivery_stream_name
        self.stream_arn = stream.attr_arn
        self.mode = mode
