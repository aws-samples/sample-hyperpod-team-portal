"""WorkspaceTemplate 编排 · 管理员 BYOI 管理 + 公开 list 给创建页用."""

from __future__ import annotations

from fastapi import HTTPException, status

from app.adapters.k8s import K8sAPIError, K8sClient
from app.core.i18n import t
from app.core.logging import get_logger

from ..api.schemas import (
    TemplateCreate,
    TemplateInfo,
    TemplatePatchAllowedImages,
)
from ..domain.cr import TEMPLATE_NS, render_template_cr
from ..domain.validators import (
    parse_cpu_millicores,
    parse_gib,
    parse_memory_mib,
)

logger = get_logger(__name__)

# 系统内置 template, Helm chart 自管, 不允许平台层删除
_SYSTEM_TEMPLATES: frozenset[str] = frozenset({
    "sagemaker-jupyter-template",
    "sagemaker-code-editor-template",
})


async def list_templates(k8s: K8sClient) -> list[TemplateInfo]:
    """列可用 WorkspaceTemplate (系统 + 自定义)."""
    items = await k8s.list_workspace_templates()
    result: list[TemplateInfo] = []
    for it in items:
        meta = it.get("metadata") or {}
        spec = it.get("spec") or {}
        primary = spec.get("primaryStorage") or {}
        default_res = (spec.get("defaultResources") or {}).get("requests") or {}
        result.append(
            TemplateInfo(
                name=meta.get("name", ""),
                display_name=spec.get("displayName", meta.get("name", "")),
                app_type=spec.get("appType", ""),
                default_image=spec.get("defaultImage", ""),
                allowed_images=spec.get("allowedImages", []),
                allow_custom_images=bool(spec.get("allowCustomImages", False)),
                default_storage_size_gib=parse_gib(
                    primary.get("defaultSize", "5Gi"), 5
                ),
                min_storage_size_gib=parse_gib(
                    primary.get("minSize", "1Gi"), 1
                ),
                max_storage_size_gib=parse_gib(
                    primary.get("maxSize", "100Gi"), 100
                ),
                default_cpu_millicores=parse_cpu_millicores(
                    default_res.get("cpu", "2")
                ),
                default_memory_mib=parse_memory_mib(
                    default_res.get("memory", "8Gi")
                ),
                description=spec.get("description"),
            )
        )
    return result


async def create_custom_template(
    k8s: K8sClient, payload: TemplateCreate
) -> dict:
    cr = render_template_cr(
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description or "",
        app_type=payload.app_type,
        default_image=payload.default_image,
        allowed_images=payload.allowed_images,
        default_cpu_millicores=payload.default_cpu_millicores,
        default_memory_mib=payload.default_memory_mib,
        default_storage_size_gib=payload.default_storage_size_gib,
        min_storage_size_gib=payload.min_storage_size_gib,
        max_storage_size_gib=payload.max_storage_size_gib,
        allow_secondary_storages=payload.allow_secondary_storages,
    )
    try:
        resp = await k8s.create_workspace_template(cr, namespace=TEMPLATE_NS)
    except K8sAPIError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s create WorkspaceTemplate failed: {exc.message}",
        ) from exc
    logger.info("dev_instance.template.create.ok", name=payload.name)
    return resp


async def patch_template_allowed_images(
    k8s: K8sClient, name: str, payload: TemplatePatchAllowedImages
) -> dict:
    """全量替换 allowedImages (不是追加, 避免遗忘幂等性)."""
    patch = {"spec": {"allowedImages": payload.allowed_images}}
    try:
        resp = await k8s.patch_workspace_template(
            name=name, patch=patch, namespace=TEMPLATE_NS
        )
    except K8sAPIError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s patch WorkspaceTemplate failed: {exc.message}",
        ) from exc
    logger.info(
        "dev_instance.template.allowed_images.update",
        name=name,
        n=len(payload.allowed_images),
    )
    return resp


async def delete_custom_template(k8s: K8sClient, name: str) -> None:
    # 保护: 不允许删系统 template (Helm 自管)
    if name in _SYSTEM_TEMPLATES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t("devinstance.system_template_undeletable", name=name),
        )
    try:
        await k8s.delete_workspace_template(name=name, namespace=TEMPLATE_NS)
    except K8sAPIError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s delete WorkspaceTemplate failed: {exc.message}",
        ) from exc
    logger.info("dev_instance.template.delete.ok", name=name)
