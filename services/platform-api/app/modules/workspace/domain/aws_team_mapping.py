"""Workspace ↔ AWS SageMaker HyperPod Team 映射 (纯函数).

AWS HyperPod Task Governance 侧的模型:
  - `Team` = AWS 内部概念, 对应一个 ComputeQuotaTarget.TeamName
  - `ComputeQuota` = 资源配额 · Team 1:1 映射 · 绑 ClusterArn
  - AWS 会为每个 Team 自动建一个 K8s namespace: `hyperpod-ns-<team-name>`

我们 DB 侧的映射:
  - `workspace.name` ≡ AWS Team Name (pattern 见 api.schemas)
  - `workspace.namespace` = `hyperpod-ns-<name>` (强制前缀, 对齐 AWS 自建 ns)
  - `workspace.sagemaker_compute_quota_id` / `_arn` 反查索引

本模块只提供**映射/构造**纯函数, 真正调 AWS 的逻辑在 orchestration 层。
参考: AWS CreateComputeQuota API shape
"""

from __future__ import annotations

from typing import Any, TypedDict

# AWS 自动给 namespace 加的前缀
_AWS_NS_PREFIX = "hyperpod-ns-"


def ensure_aws_ns_prefix(ns: str) -> str:
    """把用户输入的 namespace 规范化成 AWS 期望的 `hyperpod-ns-<name>` 格式.

    幂等: 已带前缀的直接返, 否则拼上.

    例:
        >>> ensure_aws_ns_prefix("team-a")
        'hyperpod-ns-team-a'
        >>> ensure_aws_ns_prefix("hyperpod-ns-team-a")
        'hyperpod-ns-team-a'
    """
    if ns.startswith(_AWS_NS_PREFIX):
        return ns
    return f"{_AWS_NS_PREFIX}{ns}"


def strip_aws_ns_prefix(ns: str) -> str:
    """反向: 从 `hyperpod-ns-team-a` 拆出 Team Name `team-a`.

    幂等: 不带前缀的原样返回 (大概率数据异常, 让调用方自己判).

    用于: 从 K8s namespace / AWS Team 反查 workspace.name 时的字面匹配。
    """
    if ns.startswith(_AWS_NS_PREFIX):
        return ns[len(_AWS_NS_PREFIX) :]
    return ns


def team_name_from_workspace_name(workspace_name: str) -> str:
    """workspace.name 就是 AWS Team Name (当前 M1 模型 1:1)."""
    return workspace_name


def namespace_from_team_name(team_name: str) -> str:
    """AWS 会给每个 Team 自动建一个 `hyperpod-ns-<team>` namespace."""
    return f"{_AWS_NS_PREFIX}{team_name}"


class QuotaResourceSpec(TypedDict, total=False):
    """ComputeQuotaConfig.ComputeQuotaResources 单条目 (内部数据契约).

    AWS rule (verified 2026-05-11 via ValidationException):
      `Count` is MUTUALLY EXCLUSIVE with {Accelerators, VCpu, MemoryInGiB}.
    """

    instance_type: str
    count: int
    accelerators: int | None
    v_cpu: float | None
    memory_in_gi_b: float | None


def build_compute_quota_payload(
    *,
    name: str,
    cluster_arn: str,
    resources: list[QuotaResourceSpec],
    sharing_strategy: str,
    preempt_team_tasks: str,
    fair_share_weight: int,
    description: str | None,
) -> dict[str, Any]:
    """按 AWS CreateComputeQuota shape 组装 payload.

    纯函数 · 输入已校验业务参数 → 输出 dict 给 adapter/client 发送。

    AWS rule 对 `Count` 与 {Accelerators, VCpu, MemoryInGiB} 互斥:
      - 整机配额: 只 send `Count`
      - 细粒度单资源 (e.g. "2 A10G GPUs, no whole instance"): 丢 `Count`,
        填 accelerators / v_cpu / memory_in_gi_b
      - UI 默认路径: Count>0 + accelerators=0, 这里优先 `Count`

    ResourceSharingConfig:
      - LendAndBorrow / Lend · AWS 强制要求 BorrowLimit 或 AbsoluteBorrowLimits,
        给默认 50
      - DontLend · 不能带 BorrowLimit

    """
    resources_raw: list[dict[str, Any]] = []
    for r in resources:
        item: dict[str, Any] = {"InstanceType": r["instance_type"]}
        count = r.get("count", 0)
        if count and count > 0:
            item["Count"] = count
        else:
            item["Count"] = 0
            if r.get("accelerators"):
                item["Accelerators"] = r["accelerators"]
            if r.get("v_cpu"):
                item["VCpu"] = r["v_cpu"]
            if r.get("memory_in_gi_b"):
                item["MemoryInGiB"] = r["memory_in_gi_b"]
        resources_raw.append(item)

    sharing_config: dict[str, Any] = {"Strategy": sharing_strategy}
    if sharing_strategy in ("LendAndBorrow", "Lend"):
        sharing_config["BorrowLimit"] = 50

    aws_payload: dict[str, Any] = {
        "Name": name,
        "ClusterArn": cluster_arn,
        "ComputeQuotaConfig": {
            "ComputeQuotaResources": resources_raw,
            "ResourceSharingConfig": sharing_config,
            "PreemptTeamTasks": preempt_team_tasks,
        },
        "ComputeQuotaTarget": {
            "TeamName": name,
            "FairShareWeight": fair_share_weight,
        },
        "ActivationState": "Enabled",
    }
    if description:
        aws_payload["Description"] = description
    return aws_payload


# NotFound 判定: AWS DeleteComputeQuota 删不存在 quota 时返回的错误码谱系
_AWS_NOT_FOUND_CODE_MARKERS: tuple[str, ...] = (
    "NotFound",
    "ResourceNotFound",
    "ValidationException",
)


def is_aws_not_found_error(code: str, message: str) -> bool:
    """AWS ComputeQuota delete 容忍判定.

    人工在 AWS 侧先删掉了 quota, 下次 delete_workspace 调 AWS 会返回 NotFound
    类错误 · 我们容忍, 继续清 DB。

    code 或 message 任一命中就算 NotFound:
    - code 命中: NotFoundException / ResourceNotFoundException / ValidationException
    - message: case-insensitive 含 "not found"
    """
    if any(m in code for m in _AWS_NOT_FOUND_CODE_MARKERS):
        return True
    return "not found" in message.lower()
