"""Training orchestration 层 · 业务流编排.

编排:
    - `create.py`       创建 TrainingJob (只建 HPJ CR; DDB 由 informer 写)
    - `lifecycle.py`    删除 (级联删 HPJ CR + DDB)
    - `topology.py`     按机型解析可用拓扑层级 (读 ResourceFlavor → Topology)

状态同步: 原 sync.py (request-driven) 已删, 改由 platform-worker informer
事件驱动写 DDB。详情页的实时 pods/conditions 在 router 里只读拉 (不写 DDB)。

边界: 所有 CR 渲染走 ``domain/cr.py`` · DDB 读写走 ``persistence/crud.py``
外部模块 (logs/monitoring) 不 import orchestration, 只经 HTTP + persistence.
"""

from __future__ import annotations

from app.modules.training.orchestration.create import (
    create_training_job_flow,
    preview_training_job_flow,
)
from app.modules.training.orchestration.lifecycle import delete_flow, stop_flow
from app.modules.training.orchestration.topology import resolve_topology_levels

__all__ = [
    "create_training_job_flow",
    "preview_training_job_flow",
    "delete_flow",
    "stop_flow",
    "resolve_topology_levels",
]
