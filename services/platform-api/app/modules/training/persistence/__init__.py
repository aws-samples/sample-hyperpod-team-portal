"""Training persistence 层 · DB 模型 + CRUD.

外部模块 (logs / monitoring / quota) 只通过这个包访问 training_job 表:

    from app.modules.training.persistence import crud as train_crud
    from app.modules.training.persistence.models import TrainingJob

本模块内部 orchestration/response 层同样通过此路径 import, 不直接 SELECT.
"""

from __future__ import annotations

from app.modules.training.persistence import crud
from app.modules.training.persistence.models import TrainingJob

__all__ = ["TrainingJob", "crud"]
