"""RayJob 模块 · Ray 训练 (KubeRay RayJob).

与训练任务 UI 平级, 独立 CRD (ray.io/v1 RayJob)。分层 (镜像 dynamo 模块):
    domain/         CR 渲染 (纯函数)
    orchestration/  业务流 (create / sync / lifecycle)
    api/            FastAPI router + schemas + deps
    persistence/    DDB CRUD (复用 ResourceIndex 表 resource_type='rayjob')
    response/       row → Schema 视图

状态派生在 Go platform-controller (derive_rayjob.go, 第二批), 非本模块。
第一版范围: 建 CR / 列表 / 详情 sync; 不含监控 / 日志 / 终端 / autoscaling。
"""

from __future__ import annotations

from app.modules.rayjob.api.router import rayjob_router

__all__ = ["rayjob_router"]
