"""每类任务默认优先级档名的单一解析入口.


用法:
    from app.core.priority_defaults import default_priority_class
    label = default_priority_class("train")   # → settings.priority_default_train

fallback 语义: task_type 未知 / 配成空 → settings.priority_default_fallback.
不做 WPC 存在性校验: 若档在集群里不存在, Kueue 自然回落到 priority=0 (集群侧职责).
"""

from __future__ import annotations

from app.core.config import get_settings


def default_priority_class(task_type: str) -> str:
    """按任务类型返回默认优先级档名."""
    s = get_settings()
    mapping = {
        "train": s.priority_default_train,
        "inference": s.priority_default_inference,
        "dynamo": s.priority_default_dynamo,
        "llmd": s.priority_default_llmd,
        "rayjob": s.priority_default_rayjob,
        "devinstance": s.priority_default_devinstance,
    }
    return mapping.get(task_type) or s.priority_default_fallback
