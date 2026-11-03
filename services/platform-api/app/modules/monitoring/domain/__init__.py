"""Monitoring · 领域层.

包含纯数据 (PromQL 模板) + 无 IO 的辅助 (变量替换).
涉及 K8s 查询的 "哪些节点承载了 job" 推断放在 ``orchestration/templates.py``,
因为它要调 K8s adapter, 属于业务流而非领域知识.
"""

from app.modules.monitoring.domain import promql  # noqa: F401
from app.modules.monitoring.domain.template_subst import subst_template  # noqa: F401
