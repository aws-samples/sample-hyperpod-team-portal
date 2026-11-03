"""orchestration · 业务编排层 (调 adapters + persistence + domain).

公共入口 (允许其他 module 的 orchestration 层 import):

    - create_dev_instance_flow
    - stop_flow / start_flow / delete_flow / update_flow
    - sync_from_k8s
    - register_ssm_in_sidecar
    - list_shared_pvcs
    - list_templates / create_custom_template /
      patch_template_allowed_images / delete_custom_template

禁止跨模块 import persistence/domain/api.
"""

from __future__ import annotations

from .authorized_keys import add_authorized_key_flow
from .create import create_dev_instance_flow
from .lifecycle import (
    delete_flow,
    maybe_recover_ssm,
    schedule_ssm_recovery,
    start_flow,
    stop_flow,
    sync_from_k8s,
    update_flow,
)
from .pvcs import list_permitted_mounts, list_shared_pvcs
from .resize import resize_flow
from .ssm_register import register_ssm_in_sidecar
from .templates import (
    create_custom_template,
    delete_custom_template,
    list_templates,
    patch_template_allowed_images,
)

__all__ = [
    "add_authorized_key_flow",
    "create_custom_template",
    "create_dev_instance_flow",
    "delete_custom_template",
    "delete_flow",
    "list_permitted_mounts",
    "list_shared_pvcs",
    "list_templates",
    "maybe_recover_ssm",
    "patch_template_allowed_images",
    "schedule_ssm_recovery",
    "register_ssm_in_sidecar",
    "resize_flow",
    "start_flow",
    "stop_flow",
    "sync_from_k8s",
    "update_flow",
]
