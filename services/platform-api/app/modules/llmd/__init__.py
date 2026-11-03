"""llm-d 模块 · 多机推理流水线 (分支B).

一个服务 = 一组标准 K8s 资源 (非单一 CR):
    ConfigMap / ServiceAccount / Role / RoleBinding / Deployment / Service / LeaderWorkerSet
LWS (leaderworkerset.x-k8s.io/v1) + sgl-model-gateway service-discovery 路由, 与 dynamo 并列。
分层 (镜像 dynamo 模块):
    domain/         资源渲染 (纯函数, 出 list[dict])
    orchestration/  业务流 (create / lifecycle / sync)
    api/            FastAPI router + schemas + deps
    persistence/    DDB CRUD (复用 ResourceIndex 表 resource_type='llmd')
    response/       row → Schema 视图

状态派生在 Go platform-controller, 非本模块。
最小切片: 建资源组 / 列表 / phase; 不含监控 / 日志 / 排队 / 终端 / ALB / S3 源。
"""

from __future__ import annotations

from app.modules.llmd.api.router import llmd_router

__all__ = ["llmd_router"]
