"""Training 模块 · 资产导向结构.

分层 (每层一个子包):
    domain/         CR 渲染 + 用户命令包装 (纯函数)
    orchestration/  业务流 (create / sync / delete)
    api/            FastAPI router + schemas + deps
    persistence/    ORM models + CRUD
    response/       ORM → Schema 视图构建

向后兼容 re-export (旧路径仍可用):
    - `app.modules.training.crud`   (logs/monitoring 在用)
    - `app.modules.training.models` (alembic env.py 在用)
    - `app.modules.training.router` (api/v1/router.py 在用)
    - `app.modules.training.schemas`, `app.modules.training.service`

新代码建议直接 import 分层路径, 例如::

    from app.modules.training.persistence import crud as train_crud
    from app.modules.training.domain.cr import render_hp_pytorch_job_cr
"""

from __future__ import annotations

# 主路由 · api/v1/router.py 依赖此名字
from app.modules.training.api.router import training_router

# ===== 向后兼容 re-export (shim) =====
# logs/monitoring 等老代码 `from app.modules.training import crud as train_crud`
# alembic env.py `from app.modules.training.models import ...`
from app.modules.training.api import schemas  # noqa: F401
from app.modules.training.persistence import crud, models  # noqa: F401

__all__ = ["training_router", "crud", "models", "schemas"]
