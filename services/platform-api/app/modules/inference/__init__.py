"""Inference 模块 · 资产导向结构.

分层 (镜像 training 模块):
    domain/         CR 渲染 (纯函数)
    orchestration/  业务流 (create / sync / lifecycle)
    api/            FastAPI router + schemas + deps
    persistence/    DDB CRUD (复用 ResourceIndex 表 resource_type='inference')
    response/       row → Schema 视图

阶段 1 范围:
    - 推理引擎: SGLang (锁定, 后续可加 vLLM/TGI/TRT-LLM)
    - 模型源: FSx (主) / S3 (备) / HuggingFace Hub (开发用)
    - Smart Routing: 4 策略 (roundrobin/prefixaware/kvaware/session)
    - L2 KV Cache: Helm Redis 后端
    - 监控: SGLang /metrics + DCGM + L2 命中率
"""

from __future__ import annotations

from app.modules.inference.api.router import inference_router

__all__ = ["inference_router"]
