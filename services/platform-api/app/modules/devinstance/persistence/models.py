"""DevInstance 类型 (DDB-only).

K8s Workspace CR 是 source-of-truth. DDB ResourceIndex 表只做索引 (按
workspace / creator / type 反查). 业务字段全部走 dict.

DevInstance dict 字段 (合成):
    id                   str (resource_id, uuid)
    workspace_id         str
    creator_user_id      str
    name                 str
    display_name         str
    description          str | None
    k8s_namespace        str
    k8s_workspace_name   str
    template_name        str
    app_type             str
    image                str
    cpu_request_millicores int
    memory_request_mib   int
    gpu_count            int
    efa_count            int
    storage_size_gib     int
    desired_status       str
    phase                str
    access_url           str | None
    ssm_managed_id       str | None
    last_sync_at         str | None
    last_condition_message str | None
    env_json             dict
    metadata_json        dict
    created_at / started_at / stopped_at / deleted_at / updated_at  str | None
"""

from __future__ import annotations

from typing import Any

DevInstance = dict[str, Any]

__all__ = ["DevInstance"]
