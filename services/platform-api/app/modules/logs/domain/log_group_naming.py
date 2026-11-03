"""CloudWatch log group 命名规则 (HyperPod observability add-on).

Verified on platform cluster 2026-05-11:
    /aws/sagemaker/Clusters/{cluster-tag}/{cluster-id-suffix}

其中 cluster-id-suffix 是 HyperPod cluster ARN 最后一段,
    arn:aws:sagemaker:us-west-2:123456789012:cluster/abcd1234efgh
                                                  └── 这段 abcd1234efgh
"""

from __future__ import annotations


def cluster_id_suffix_from_arn(cluster_arn: str) -> str:
    """``arn:aws:...:cluster/abcd1234efgh`` -> ``abcd1234efgh``."""
    return cluster_arn.rsplit("/", 1)[-1]


def build_log_group(cluster_tag: str, cluster_arn: str) -> str:
    """Compose the HyperPod container log group name."""
    return (
        f"/aws/sagemaker/Clusters/{cluster_tag}/"
        f"{cluster_id_suffix_from_arn(cluster_arn)}"
    )


def split_log_group(log_group: str) -> tuple[str, str] | None:
    """``/aws/sagemaker/Clusters/{tag}/{suffix}`` -> ``(tag, suffix)``。

    build_log_group 的逆运算。用于 resolver 直接吃预配置的完整 log group
    (settings.log_group_name), 反解出 cluster_tag + cluster-id-suffix 填 ctx,
    从而跳过 ws_get + SageMaker DescribeCluster。格式不符返回 None (调用方回退)。
    """
    prefix = "/aws/sagemaker/Clusters/"
    if not log_group.startswith(prefix):
        return None
    rest = log_group[len(prefix):].strip("/")
    parts = rest.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]
