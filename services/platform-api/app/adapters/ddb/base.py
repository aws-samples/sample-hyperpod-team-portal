"""通用 DDB Repository helper. 5 个 Repository 复用此层.

设计原则:
    - 所有 item 都是 dict (DDB 原生), 业务层做 dict ↔ pydantic 转换
    - 没有 ORM, 没有 lazy load, 没有 unit-of-work
    - put/get/query/update/delete 5 个动词足以覆盖 5 张表所有需求
    - condition expression 暴露给调用方 (e.g. 创建时 attribute_not_exists 防重)

为什么不直接用 aioboto3.Table 暴露给业务:
    - 集中错误转译: ConditionalCheckFailed → ItemAlreadyExists / ItemNotFound
    - 集中分页: query_all 帮调用方自动翻页
    - 集中投影/属性命名: 万一改 GSI 投影只动这里
"""

from __future__ import annotations

from typing import Any

from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from app.adapters.ddb.client import ddb_client, ddb_resource


class ItemAlreadyExists(Exception):
    """put_item 带 attribute_not_exists 失败."""


class ItemNotFound(Exception):
    """update/delete 带 attribute_exists 失败 / get_item 找不到."""


class TransactionConflict(Exception):
    """TransactWriteItems 内任一 condition 失败 → 整个事务回滚."""


# transact_write 用低层 client API, 需要序列化成 DDB 类型格式 ({"S": "..."} / {"N": "1"} ...)
_SERIALIZER = TypeSerializer()


def _serialize_value(v: Any) -> Any:
    """boto3 TypeSerializer wrapper, 单值 -> DDB 类型字典."""
    return _SERIALIZER.serialize(v)


def _serialize_dict(d: dict[str, Any]) -> dict[str, Any]:
    """整个 dict 每个 value 序列化."""
    return {k: _SERIALIZER.serialize(v) for k, v in d.items()}


# ---------------- write ----------------

async def put_item(table_name: str, item: dict[str, Any], *, ensure_new: bool = False) -> None:
    """写入 item. ensure_new=True 时 PK 已存在抛 ItemAlreadyExists.

    注意 PK/SK 字段名取决于具体表; condition 用 attribute_not_exists(<PK>).
    暂只判 PK; 复合主键的表 (WorkspaceMembers/ResourceIndex/AuditLog) 调用方自行传 condition.
    """
    async with ddb_resource() as ddb:
        table = await ddb.Table(table_name)
        kwargs: dict[str, Any] = {"Item": item}
        if ensure_new:
            # 取 dict 第一个 key 作为 PK (调用方保证 item 第一个 key 是 PK)
            pk_attr = next(iter(item))
            kwargs["ConditionExpression"] = f"attribute_not_exists({pk_attr})"
        try:
            await table.put_item(**kwargs)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ItemAlreadyExists(table_name) from e
            raise


async def put_item_conditional(
    table_name: str,
    item: dict[str, Any],
    *,
    condition_expression: str,
    expression_names: dict[str, str] | None = None,
    expression_values: dict[str, Any] | None = None,
) -> bool:
    """带自定义 ConditionExpression 的 put. 条件满足写入返 True, 不满足返 False (不抛).

    用于 informer 幂等写: 仅当 attribute_not_exists(pk) OR k8s_resource_version < :rv 才写。
    DynamoDB 在服务端原子求值条件, 不存在 read-modify-write race, 任意副本数安全。
    """
    async with ddb_resource() as ddb:
        table = await ddb.Table(table_name)
        kwargs: dict[str, Any] = {
            "Item": item,
            "ConditionExpression": condition_expression,
        }
        if expression_names:
            kwargs["ExpressionAttributeNames"] = expression_names
        if expression_values:
            kwargs["ExpressionAttributeValues"] = expression_values
        try:
            await table.put_item(**kwargs)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise


async def update_item_conditional(
    table_name: str,
    key: dict[str, Any],
    *,
    update_expression: str,
    condition_expression: str,
    expression_names: dict[str, str] | None = None,
    expression_values: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    """带自定义 ConditionExpression 的部分更新 (UpdateExpression 只 SET 指定字段)。

    返回 (ok, old_item):
        ok=True  → 条件满足, 已更新; old_item=None
        ok=False → 条件失败; old_item=条件失败时的当前行 (ReturnValuesOnConditionCheckFailure
                   =ALL_OLD), 行不存在时 old_item=None。
    调用方据此区分: ok=False 且 old_item 有值 → 行存在但条件不满足 (如去重命中);
                    ok=False 且 old_item=None → 行不存在。
    (真 DDB 实测 2026-06-09 确认此区分有效。)
    """
    async with ddb_resource() as ddb:
        table = await ddb.Table(table_name)
        kwargs: dict[str, Any] = {
            "Key": key,
            "UpdateExpression": update_expression,
            "ConditionExpression": condition_expression,
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        }
        if expression_names:
            kwargs["ExpressionAttributeNames"] = expression_names
        if expression_values:
            kwargs["ExpressionAttributeValues"] = expression_values
        try:
            await table.update_item(**kwargs)
            return True, None
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False, e.response.get("Item")
            raise


async def update_item(
    table_name: str,
    key: dict[str, Any],
    update_expression: str,
    expression_values: dict[str, Any] | None = None,
    *,
    expression_names: dict[str, str] | None = None,
    require_exists: bool = True,
) -> dict[str, Any]:
    """update_item + 自动 ConditionalCheckFailed → ItemNotFound 转译.

    expression_values 可为空 (如纯 REMOVE 表达式, DDB 不允许空 values dict)。

    Returns: 更新后的完整 item (ReturnValues=ALL_NEW).
    """
    async with ddb_resource() as ddb:
        table = await ddb.Table(table_name)
        kwargs: dict[str, Any] = {
            "Key": key,
            "UpdateExpression": update_expression,
            "ReturnValues": "ALL_NEW",
        }
        if expression_values:
            kwargs["ExpressionAttributeValues"] = expression_values
        if expression_names:
            kwargs["ExpressionAttributeNames"] = expression_names
        if require_exists:
            pk_attr = next(iter(key))
            cond = f"attribute_exists({pk_attr})"
            kwargs["ConditionExpression"] = cond
        try:
            resp = await table.update_item(**kwargs)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ItemNotFound(f"{table_name} key={key}") from e
            raise
        return resp.get("Attributes", {})


async def delete_item(
    table_name: str,
    key: dict[str, Any],
    *,
    require_exists: bool = False,
) -> None:
    async with ddb_resource() as ddb:
        table = await ddb.Table(table_name)
        kwargs: dict[str, Any] = {"Key": key}
        if require_exists:
            pk_attr = next(iter(key))
            kwargs["ConditionExpression"] = f"attribute_exists({pk_attr})"
        try:
            await table.delete_item(**kwargs)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ItemNotFound(f"{table_name} key={key}") from e
            raise


# ---------------- read ----------------

async def get_item(table_name: str, key: dict[str, Any]) -> dict[str, Any] | None:
    async with ddb_resource() as ddb:
        table = await ddb.Table(table_name)
        resp = await table.get_item(Key=key, ConsistentRead=True)
    return resp.get("Item")


async def batch_get_items(
    table_name: str,
    keys: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """BatchGetItem; 单批最多 100 条, 自动分批."""
    if not keys:
        return []
    out: list[dict[str, Any]] = []
    async with ddb_resource() as ddb:
        for i in range(0, len(keys), 100):
            batch = keys[i : i + 100]
            resp = await ddb.batch_get_item(
                RequestItems={table_name: {"Keys": batch, "ConsistentRead": True}}
            )
            out.extend(resp.get("Responses", {}).get(table_name, []))
    return out


async def query(
    table_name: str,
    key_condition_expression: str,
    expression_values: dict[str, Any],
    *,
    expression_names: dict[str, str] | None = None,
    index_name: str | None = None,
    filter_expression: str | None = None,
    scan_index_forward: bool = True,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Query, 自动翻页直到完结或达到 limit."""
    items: list[dict[str, Any]] = []
    last_key: dict[str, Any] | None = None
    async with ddb_resource() as ddb:
        table = await ddb.Table(table_name)
        while True:
            kwargs: dict[str, Any] = {
                "KeyConditionExpression": key_condition_expression,
                "ExpressionAttributeValues": expression_values,
                "ScanIndexForward": scan_index_forward,
            }
            if expression_names:
                kwargs["ExpressionAttributeNames"] = expression_names
            if index_name:
                kwargs["IndexName"] = index_name
            if filter_expression:
                kwargs["FilterExpression"] = filter_expression
            if last_key:
                kwargs["ExclusiveStartKey"] = last_key
            if limit:
                kwargs["Limit"] = limit - len(items)
            resp = await table.query(**kwargs)
            items.extend(resp.get("Items", []))
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
            if limit and len(items) >= limit:
                items = items[:limit]
                break
    return items


async def scan_all(table_name: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    """全表扫. 仅小表 (Users / Workspaces) 用; AuditLog/ResourceIndex 禁用."""
    items: list[dict[str, Any]] = []
    last_key: dict[str, Any] | None = None
    async with ddb_resource() as ddb:
        table = await ddb.Table(table_name)
        while True:
            kwargs: dict[str, Any] = {}
            if last_key:
                kwargs["ExclusiveStartKey"] = last_key
            if limit:
                kwargs["Limit"] = limit - len(items)
            resp = await table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
            if limit and len(items) >= limit:
                items = items[:limit]
                break
    return items


# ---------------- transactions ----------------

def put_op(
    table_name: str,
    item: dict[str, Any],
    *,
    condition_expression: str | None = None,
    expression_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """构造一个 TransactWriteItems 用的 Put 操作 dict."""
    op: dict[str, Any] = {
        "TableName": table_name,
        "Item": _serialize_dict(item),
    }
    if condition_expression:
        op["ConditionExpression"] = condition_expression
    if expression_names:
        op["ExpressionAttributeNames"] = expression_names
    return {"Put": op}


def update_op(
    table_name: str,
    key: dict[str, Any],
    update_expression: str,
    expression_values: dict[str, Any],
    *,
    expression_names: dict[str, str] | None = None,
    condition_expression: str | None = None,
) -> dict[str, Any]:
    """构造一个 TransactWriteItems 用的 Update 操作 dict."""
    op: dict[str, Any] = {
        "TableName": table_name,
        "Key": _serialize_dict(key),
        "UpdateExpression": update_expression,
        "ExpressionAttributeValues": _serialize_dict(expression_values),
    }
    if expression_names:
        op["ExpressionAttributeNames"] = expression_names
    if condition_expression:
        op["ConditionExpression"] = condition_expression
    return {"Update": op}


def delete_op(
    table_name: str,
    key: dict[str, Any],
    *,
    condition_expression: str | None = None,
    expression_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """构造一个 TransactWriteItems 用的 Delete 操作 dict."""
    op: dict[str, Any] = {
        "TableName": table_name,
        "Key": _serialize_dict(key),
    }
    if condition_expression:
        op["ConditionExpression"] = condition_expression
    if expression_names:
        op["ExpressionAttributeNames"] = expression_names
    return {"Delete": op}


async def transact_write(operations: list[dict[str, Any]]) -> None:
    """跨多 item 的 atomic 事务. 任一 condition 失败整体回滚.

    operations: 由 put_op / update_op / delete_op 构造的 dict 列表 (≤100).

    抛 TransactionConflict 当任一 condition 失败 (ConditionalCheckFailed).
    """
    if not operations:
        return
    if len(operations) > 100:
        raise ValueError(
            f"TransactWriteItems max 100 ops, got {len(operations)}"
        )
    async with ddb_client() as c:
        try:
            await c.transact_write_items(TransactItems=operations)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "TransactionCanceledException":
                # 详情在 CancellationReasons[i].Code, e.g. "ConditionalCheckFailed"
                reasons = e.response.get("CancellationReasons") or []
                summary = ",".join(r.get("Code", "?") for r in reasons)
                raise TransactionConflict(
                    f"transact_write canceled: {summary}"
                ) from e
            raise
