"""节点健康检查规则（纯函数）

职责:
- 融合 SageMaker `node-health-status` label 与 K8s Ready condition，输出统一健康态
- 不做 IO，不依赖 SQLAlchemy / K8s 客户端

枚举 (node_status.health_status):
- Schedulable                   · 节点就绪，可调度
- UnschedulableSchedulingDisabled · 节点被 cordon
- Unhealthy                     · DHC 检测失败 / NotReady
"""

from __future__ import annotations

from typing import Literal

HealthStatus = Literal["Schedulable", "UnschedulableSchedulingDisabled", "Unhealthy"]


def derive_health_status(
    sagemaker_status: str | None,
    k8s_ready: bool,
) -> HealthStatus:
    """融合 SageMaker node-health-status label + K8s Ready 条件

    优先级: SageMaker label > K8s Ready fallback

    SageMaker label 取值（AWS 官方）:
    - Schedulable
    - Unschedulable
    - UnschedulablePendingReplacement
    - Unhealthy
    """
    if sagemaker_status:
        if sagemaker_status == "Schedulable":
            return "Schedulable"
        if sagemaker_status == "Unhealthy":
            return "Unhealthy"
        if "Unschedulable" in sagemaker_status:
            return "UnschedulableSchedulingDisabled"
    return "Schedulable" if k8s_ready else "Unhealthy"


def derive_sync_status(
    cluster_type: str,
    db_ig_count: int,
    aws_ig_count: int | None,
    had_aws_error: bool,
) -> str:
    """推导 cluster summary 的 sync_status 三态

    - aws_unavailable : AWS 调用失败 或 非 hyperpod 集群无 AWS 侧数据
    - in_sync         : DB IG 数 == AWS IG 数
    - out_of_sync     : 数量不一致（触发上层告警 / 重同步）
    """
    if cluster_type != "hyperpod":
        return "aws_unavailable"
    if had_aws_error or aws_ig_count is None:
        return "aws_unavailable"
    return "in_sync" if db_ig_count == aws_ig_count else "out_of_sync"
