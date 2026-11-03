"""api · HTTP 路由 + Pydantic DTO + FastAPI deps.

对外导出:
    - router: FastAPI APIRouter (挂到 /api/v1)
    - schemas: 所有 request/response Pydantic model (老代码/测试都走这里)
"""

from __future__ import annotations

from .router import router
from .schemas import (
    AccessInfo,
    DevInstanceCreate,
    DevInstanceDetail,
    DevInstanceListItem,
    DevInstanceUpdate,
    SharedPVCInfo,
    TemplateCreate,
    TemplateInfo,
    TemplatePatchAllowedImages,
    VolumeMount,
)

__all__ = [
    "AccessInfo",
    "DevInstanceCreate",
    "DevInstanceDetail",
    "DevInstanceListItem",
    "DevInstanceUpdate",
    "SharedPVCInfo",
    "TemplateCreate",
    "TemplateInfo",
    "TemplatePatchAllowedImages",
    "VolumeMount",
    "router",
]
