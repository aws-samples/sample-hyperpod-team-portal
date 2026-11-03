"""Cluster 模块 response 层 · ORM → dict 视图构建

职责:
- 把 persistence 层返的 ORM 对象变成 HTTP 返回的 dict / 视图
- 不做 IO，纯函数
"""

from app.modules.cluster.response import builders as builders
