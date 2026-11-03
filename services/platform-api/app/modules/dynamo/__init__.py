"""Dynamo 模块 · 多机推理第二条流水线.

DynamoGraphDeployment (nvidia.com/v1beta1) — 跨机 TP/EP, 与 IEC 单机多副本并列。
分层 (镜像 inference 模块):
    domain/         CR 渲染 (纯函数)
    orchestration/  业务流 (create / lifecycle)
    api/            FastAPI router + schemas + deps
    persistence/    DDB CRUD (复用 ResourceIndex 表 resource_type='dynamo')
    response/       row → Schema 视图

状态派生在 Go platform-controller (derive_dynamo.go), 非本模块。
最小切片范围: 建 CR / 列表 / phase; 不含监控 / 日志 / 排队 / 终端 / ALB / gang / share。
"""

from __future__ import annotations

from app.modules.dynamo.api.router import dynamo_router

__all__ = ["dynamo_router"]
