"""Cluster 模块持久层 (DDB-only / AWS-as-SoT).

历史: 此处曾导出 ORM models (Cluster / InstanceGroup / NodeStatus /
ResourceQuota / NodeOperationLog). 切到 DDB + AWS-as-SoT 后, models
全部退化为 dict type alias, 见 ``persistence.models``.
"""

from app.modules.cluster.persistence import crud as crud
from app.modules.cluster.persistence.models import Cluster as Cluster
from app.modules.cluster.persistence.models import InstanceGroup as InstanceGroup
from app.modules.cluster.persistence.models import (
    NodeOperationLog as NodeOperationLog,
)
from app.modules.cluster.persistence.models import NodeStatus as NodeStatus
from app.modules.cluster.persistence.models import ResourceQuota as ResourceQuota
