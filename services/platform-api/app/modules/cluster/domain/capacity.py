"""容量聚合算法（纯函数）

职责:
- GPU 使用率百分比
- SageMaker instance_type → flavor key 映射
- gpu_type prefix map（gpu 族 → instance family 前缀）

所有函数不做 IO，便于单测。
"""

from __future__ import annotations

# H100 / A100 / A10G → SageMaker ml.* 前缀
_GPU_TYPE_PREFIX: dict[str, str] = {
    "H100": "ml.p5",
    "A100": "ml.p4d",
    "A10G": "ml.g5",
}


def gpu_usage_pct(gpu_used: int, gpu_total: int) -> float:
    """GPU 使用率百分比（保留 2 位小数，total=0 返 0.0）"""
    if gpu_total <= 0:
        return 0.0
    return round((gpu_used / gpu_total * 100.0), 2)


def flavor_key_from_instance_type(instance_type: str) -> str:
    """SageMaker instance_type → flavor 前缀 key

    规则:
    - 'ml.g5.xlarge'     → 'g5'
    - 'ml.p5.48xlarge'   → 'p5'
    - 'ml.m5.xlarge'     → 'cpu'   (m/c/r 系列统一映射为 cpu)
    - 其余 / 格式异常     → 'unknown'
    """
    parts = instance_type.split(".")
    if len(parts) < 2:
        return "unknown"
    family = parts[1]
    if family.startswith(("m", "c", "r")):
        return "cpu"
    return family


def instance_type_prefix_for_gpu(gpu_type: str) -> str | None:
    """'H100' → 'ml.p5'；未知返 None（由上层决定是否走 labels 精确匹配）"""
    return _GPU_TYPE_PREFIX.get(gpu_type.upper())


def quota_usage_pct(used: int, quota: int) -> float:
    """配额使用率（同 gpu_usage_pct 语义，独立暴露便于语义）"""
    return gpu_usage_pct(used, quota)
