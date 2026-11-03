"""TrainingJob 类型 (DDB-only).

K8s HyperPodPyTorchJob CR 是 SoT; DDB ResourceIndex 表只做反查索引.
"""

from __future__ import annotations

from typing import Any

TrainingJob = dict[str, Any]

__all__ = ["TrainingJob"]
