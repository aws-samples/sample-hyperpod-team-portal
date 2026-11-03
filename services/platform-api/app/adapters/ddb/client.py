"""aioboto3 DynamoDB lazy singleton.

为什么 lazy: aioboto3 Session 创建涉及 endpoint 解析 + 凭证链探测,
启动期不连可让 main.py 立即起来, 第一次 DDB 调用才连.

为什么 module-level singleton 而非 FastAPI Depends:
    - DDB client 是无状态 + 线程安全, 全进程共享 1 个最划算
    - aioboto3 内部用 aiohttp 连接池, 复用 socket
    - 测试时通过 reset_ddb_session() + 设置 ddb_endpoint_url=http://localhost:8000 切到 DynamoDB Local 或 moto

异常策略:
    - 调用方 catch botocore.exceptions.ClientError, 不在这里包一层
    - 健康检查走 describe_table(ALL_TABLES[0])
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import aioboto3

from app.core.config import get_settings

_session: aioboto3.Session | None = None


def _get_session() -> aioboto3.Session:
    global _session
    if _session is None:
        # 显式带 profile (跟 fsx/identitystore adapter 一致). 不传时 aioboto3 走
        # 默认凭证链, 多 account 环境下可能连错 account → ResourceNotFound。
        # DDB Local 模式 (ddb_endpoint_url 设了) 用 dummy 凭证, 不需要 profile。
        s = get_settings()
        if s.aws_profile and not s.ddb_endpoint_url:
            _session = aioboto3.Session(profile_name=s.aws_profile)
        else:
            _session = aioboto3.Session()
    return _session


def reset_ddb_session() -> None:
    """测试用: 强制下次重新建 Session (e.g. 切 endpoint_url)."""
    global _session
    _session = None


def _kwargs() -> dict[str, str]:
    s = get_settings()
    kw: dict[str, str] = {
        "region_name": s.aws_region,
    }
    if s.ddb_endpoint_url:
        kw["endpoint_url"] = s.ddb_endpoint_url
        kw["aws_access_key_id"] = "dummy"
        kw["aws_secret_access_key"] = "dummy"
    return kw


@asynccontextmanager
async def ddb_resource() -> AsyncIterator:  # type: ignore[type-arg]
    """高层资源 API. 用于 Table 对象 (item-level 操作).

    用法:
        async with ddb_resource() as ddb:
            table = await ddb.Table(USERS_TABLE)
            await table.put_item(Item={...})
    """
    session = _get_session()
    async with session.resource("dynamodb", **_kwargs()) as ddb:
        yield ddb


@asynccontextmanager
async def ddb_client() -> AsyncIterator:  # type: ignore[type-arg]
    """低层 client API. 用于 admin (describe_table / list_tables / 健康检查)."""
    session = _get_session()
    async with session.client("dynamodb", **_kwargs()) as client:
        yield client


async def ping() -> bool:
    """健康检查: list_tables 一次, 200 即视为通."""
    from app.adapters.ddb.tables import ALL_TABLES

    async with ddb_client() as c:
        resp = await c.list_tables()
    found = set(resp.get("TableNames", []))
    return all(t in found for t in ALL_TABLES)
