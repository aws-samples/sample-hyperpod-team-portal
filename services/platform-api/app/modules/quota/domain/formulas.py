"""Quota 单位换算 + 聚合公式 (纯函数).

用途:
- K8s quantity 字符串 → 标准单位 (cores / GiB / int count)
- ComputeQuota resources[] × count → 聚合 totals

边界:
- 零 IO · 零副作用 · 输入→输出 · 便于单测
- 不引用任何 AWS/K8s 客户端
"""

from __future__ import annotations

_BYTES_IN_GI = 1024**3

# ComputeQuota resources[] 里标识"加速器"的 K8s resource name 集合
# (Kueue ClusterQueue.status 里会以这些 key 暴露 GPU/Neuron 用量)
ACCELERATOR_RESOURCE_KEYS: frozenset[str] = frozenset(
    {"nvidia.com/gpu", "aws.amazon.com/neurondevice"}
)


# ============================================================
# K8s quantity 解析 (与 Kueue ClusterQueue.status.flavorsUsage 对齐)
# ============================================================

def parse_cpu_cores(raw: str | int | float | None) -> float:
    """K8s CPU quantity → cores (float).

    '2' -> 2.0; '2000m' -> 2.0; 2 -> 2.0; None/空/非法 -> 0.0
    """
    if raw is None:
        return 0.0
    s = str(raw).strip()
    if not s:
        return 0.0
    if s.endswith("m"):
        try:
            return float(s[:-1]) / 1000.0
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_memory_gib(raw: str | int | float | None) -> float:
    """K8s memory quantity → GiB (float).

    二进制后缀优先 (Ki/Mi/Gi/Ti/Pi), 其次十进制 (K/M/G/T/P),
    最后无后缀按 bytes 解读.

    '8Gi' -> 8.0; '8192Mi' -> 8.0; '8589934592' -> 8.0; None -> 0.0
    """
    if raw is None:
        return 0.0
    s = str(raw).strip()
    if not s:
        return 0.0

    bin_mult: dict[str, float] = {
        "Ki": 1024.0, "Mi": 1024.0**2, "Gi": 1024.0**3,
        "Ti": 1024.0**4, "Pi": 1024.0**5,
    }
    for suf, mult in bin_mult.items():
        if s.endswith(suf):
            try:
                return float(s[: -len(suf)]) * mult / _BYTES_IN_GI
            except ValueError:
                return 0.0

    dec_mult: dict[str, float] = {"K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "P": 1e15}
    for suf, mult in dec_mult.items():
        if s.endswith(suf):
            try:
                return float(s[: -len(suf)]) * mult / _BYTES_IN_GI
            except ValueError:
                return 0.0

    # 无后缀 = bytes
    try:
        return float(s) / _BYTES_IN_GI
    except ValueError:
        return 0.0


def parse_int_count(raw: str | int | float | None) -> int:
    """K8s count (GPU / Neuron 等整数资源) → int.

    GPU 理论上不会带 'm' 后缀, 但保险兼容.
    """
    if raw is None:
        return 0
    s = str(raw).strip()
    if not s:
        return 0
    if s.endswith("m"):
        try:
            return int(float(s[:-1]) / 1000.0)
        except ValueError:
            return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


# ============================================================
# ComputeQuota totals 聚合 (per-instance × count)
# ============================================================

def aggregate_totals(
    resources: list[tuple[int, int, float, float]],
) -> tuple[int, float, float]:
    """按 resources 合计 (accelerators, v_cpu, memory_in_gi_b).

    Args:
        resources: [(count, accelerators, v_cpu, memory_in_gi_b), ...]
            accelerators/v_cpu/memory 是"每实例"值, count 是实例数

    Returns:
        (total_accelerators, total_v_cpu, total_memory_in_gi_b)
        浮点数保留两位小数
    """
    total_accel = 0
    total_vcpu = 0.0
    total_mem = 0.0
    for count, accel, vcpu, mem in resources:
        total_accel += accel * count
        total_vcpu += vcpu * count
        total_mem += mem * count
    return total_accel, round(total_vcpu, 2), round(total_mem, 2)
