"""Training domain 层 · 纯函数 (无 IO).

- `cr.py`: HyperPodPyTorchJob CR 渲染
- `hyperpodrun.py`: 把用户命令包装成 hyperpod elastic agent 入口

外部禁止绕过本层直接拼 CR dict —— 所有 CR 合规红线都靠这两个函数集中守.
"""

from __future__ import annotations

from app.modules.training.domain.cr import render_hp_pytorch_job_cr
from app.modules.training.domain.hyperpodrun import (
    USER_SCRIPT_PATH,
    wrap_with_hyperpodrun,
)

__all__ = [
    "USER_SCRIPT_PATH",
    "render_hp_pytorch_job_cr",
    "wrap_with_hyperpodrun",
]
