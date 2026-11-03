"""Monitoring · 业务流.

``templates.py``: 给 training job / dev instance 渲染已替换好占位符的模板清单.
    - 依赖 K8s adapter 推断 ``node_regex``
    - 依赖 domain.promql 提供模板列表
    - 依赖 domain.template_subst 做字符串替换

``kueue_queues.py``: 队列页表格 —— 跨 ws 聚合当前排队数 (直接发 instant query).
"""

from app.modules.monitoring.orchestration.kueue_queues import (  # noqa: F401
    list_kueue_queue_rows,
)
from app.modules.monitoring.orchestration.templates import (  # noqa: F401
    resolve_dev_instance_kpi_templates,
    resolve_dev_instance_templates,
    resolve_dynamo_templates,
    resolve_inference_templates,
    resolve_llmd_templates,
    resolve_pods_node_regex,
    resolve_rayjob_templates,
    resolve_training_templates,
)
