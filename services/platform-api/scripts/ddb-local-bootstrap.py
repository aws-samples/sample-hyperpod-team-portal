#!/usr/bin/env python3
"""DynamoDB Local 5 张表创建/删除脚本.

用法:
    docker run -d -p 8000:8000 amazon/dynamodb-local:2.5.4
    python ddb-local-bootstrap.py
    python ddb-local-bootstrap.py --delete   # 反向删表

环境变量 (可选):
    DDB_ENDPOINT_URL 默认 http://localhost:8000
    AWS_REGION 默认 us-west-2
    TABLE_PREFIX 默认 hypd-local-

依赖: 只 import boto3 + sys + argparse + os, 不依赖 platform-api app 模块.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import boto3
from botocore.exceptions import ClientError


# ---------------- 配置 ----------------

DDB_ENDPOINT_URL = os.environ.get("DDB_ENDPOINT_URL", "http://localhost:8000")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_PREFIX = os.environ.get("TABLE_PREFIX", "hypd-local-")

# DynamoDB Local 不校验凭证, 但 boto3 必须给非空 dummy 值.
DUMMY_AK = "dummy"
DUMMY_SK = "dummy"

COMMON_TAGS = [
    {"Key": "Project", "Value": "hyperpod-platform"},
    {"Key": "ManagedBy", "Value": "cli-bootstrap"},
    {"Key": "Component", "Value": "platform-api"},
]


# ---------------- 5 张表 schema ----------------
# 与 ddb-create-tables.sh 中 JSON 完全一致, 来自 .
# 注意: DynamoDB Local 不支持 PITR / TTL / SSE 部分 API, 我们仅在能用时启用.

def _table_specs(prefix: str) -> list[dict[str, Any]]:
    return [
        {
            "TableName": f"{prefix}Users",
            "BillingMode": "PAY_PER_REQUEST",
            "AttributeDefinitions": [
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "cognito_sub", "AttributeType": "S"},
            ],
            "KeySchema": [
                {"AttributeName": "user_id", "KeyType": "HASH"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "cognito_sub-index",
                    "KeySchema": [
                        {"AttributeName": "cognito_sub", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            "_ttl_attr": None,
        },
        {
            "TableName": f"{prefix}Workspaces",
            "BillingMode": "PAY_PER_REQUEST",
            "AttributeDefinitions": [
                {"AttributeName": "workspace_id", "AttributeType": "S"},
                {"AttributeName": "compute_quota_id", "AttributeType": "S"},
                {"AttributeName": "owner_user_id", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
            ],
            "KeySchema": [
                {"AttributeName": "workspace_id", "KeyType": "HASH"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "compute_quota_id-index",
                    "KeySchema": [
                        {"AttributeName": "compute_quota_id", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "owner-index",
                    "KeySchema": [
                        {"AttributeName": "owner_user_id", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            "_ttl_attr": None,
        },
        {
            "TableName": f"{prefix}WorkspaceMembers",
            "BillingMode": "PAY_PER_REQUEST",
            "AttributeDefinitions": [
                {"AttributeName": "workspace_id", "AttributeType": "S"},
                {"AttributeName": "user_id", "AttributeType": "S"},
            ],
            "KeySchema": [
                {"AttributeName": "workspace_id", "KeyType": "HASH"},
                {"AttributeName": "user_id", "KeyType": "RANGE"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "user-index",
                    "KeySchema": [
                        {"AttributeName": "user_id", "KeyType": "HASH"},
                        {"AttributeName": "workspace_id", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            "_ttl_attr": None,
        },
        {
            "TableName": f"{prefix}MountPermissions",
            "BillingMode": "PAY_PER_REQUEST",
            "AttributeDefinitions": [
                {"AttributeName": "workspace_id", "AttributeType": "S"},
                {"AttributeName": "perm_key", "AttributeType": "S"},
                {"AttributeName": "username", "AttributeType": "S"},
            ],
            "KeySchema": [
                {"AttributeName": "workspace_id", "KeyType": "HASH"},
                {"AttributeName": "perm_key", "KeyType": "RANGE"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "username-index",
                    "KeySchema": [
                        {"AttributeName": "username", "KeyType": "HASH"},
                        {"AttributeName": "workspace_id", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            "_ttl_attr": None,
        },
        {
            "TableName": f"{prefix}ResourceIndex",
            "BillingMode": "PAY_PER_REQUEST",
            "AttributeDefinitions": [
                {"AttributeName": "workspace_id", "AttributeType": "S"},
                {"AttributeName": "resource_key", "AttributeType": "S"},
                {"AttributeName": "creator_user_id", "AttributeType": "S"},
                {"AttributeName": "resource_type", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
                {"AttributeName": "active_ws", "AttributeType": "S"},
                {"AttributeName": "resource_id", "AttributeType": "S"},
            ],
            "KeySchema": [
                {"AttributeName": "workspace_id", "KeyType": "HASH"},
                {"AttributeName": "resource_key", "KeyType": "RANGE"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "creator-index",
                    "KeySchema": [
                        {"AttributeName": "creator_user_id", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "type-time-index",
                    "KeySchema": [
                        {"AttributeName": "resource_type", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "active-index",
                    "KeySchema": [
                        {"AttributeName": "active_ws", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "resource_id-index",
                    "KeySchema": [
                        {"AttributeName": "resource_id", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            "_ttl_attr": None,
        },
        {
            "TableName": f"{prefix}AuditLog",
            "BillingMode": "PAY_PER_REQUEST",
            "AttributeDefinitions": [
                {"AttributeName": "scope_key", "AttributeType": "S"},
                {"AttributeName": "event_key", "AttributeType": "S"},
                {"AttributeName": "actor_user_id", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
            ],
            "KeySchema": [
                {"AttributeName": "scope_key", "KeyType": "HASH"},
                {"AttributeName": "event_key", "KeyType": "RANGE"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "actor-index",
                    "KeySchema": [
                        {"AttributeName": "actor_user_id", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            "_ttl_attr": "expire_at",
        },
        {
            "TableName": f"{prefix}ResourceTemplates",
            "BillingMode": "PAY_PER_REQUEST",
            "AttributeDefinitions": [
                {"AttributeName": "workspace_id", "AttributeType": "S"},
                {"AttributeName": "sort_key", "AttributeType": "S"},
            ],
            "KeySchema": [
                {"AttributeName": "workspace_id", "KeyType": "HASH"},
                {"AttributeName": "sort_key", "KeyType": "RANGE"},
            ],
            "_ttl_attr": None,
        },
        {
            "TableName": f"{prefix}ApiTokens",
            "BillingMode": "PAY_PER_REQUEST",
            "AttributeDefinitions": [
                {"AttributeName": "username", "AttributeType": "S"},
                {"AttributeName": "token_hash", "AttributeType": "S"},
            ],
            "KeySchema": [
                {"AttributeName": "username", "KeyType": "HASH"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "token_hash-index",
                    "KeySchema": [
                        {"AttributeName": "token_hash", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            "_ttl_attr": None,
        },
    ]


def _make_client():
    """构造连接 DynamoDB Local 的 client."""
    return boto3.client(
        "dynamodb",
        endpoint_url=DDB_ENDPOINT_URL,
        region_name=AWS_REGION,
        aws_access_key_id=DUMMY_AK,
        aws_secret_access_key=DUMMY_SK,
    )


def _table_exists(client, name: str) -> bool:
    try:
        client.describe_table(TableName=name)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


def _wait_active(client, name: str) -> None:
    print(f"  等待 {name} 进入 ACTIVE ...", flush=True)
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=name)


def _wait_deleted(client, name: str) -> None:
    print(f"  等待 {name} 删除完成 ...", flush=True)
    waiter = client.get_waiter("table_not_exists")
    waiter.wait(TableName=name)


def _try_enable_ttl(client, name: str, attr: str) -> None:
    """DynamoDB Local 支持 TTL API, 但行为是 stub. 失败容忍."""
    try:
        client.update_time_to_live(
            TableName=name,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": attr},
        )
        print(f"  启用 TTL: {name} (attr={attr})", flush=True)
    except ClientError as exc:
        print(
            f"  跳过 TTL ({name}): {exc.response['Error']['Code']} — DynamoDB Local 可能不支持",
            flush=True,
        )


def _try_apply_tags(client, name: str) -> None:
    """DynamoDB Local 不支持 tag-resource, 失败容忍, 真实 AWS 会成功."""
    try:
        desc = client.describe_table(TableName=name)
        arn = desc["Table"]["TableArn"]
        client.tag_resource(ResourceArn=arn, Tags=COMMON_TAGS)
        print(f"  打 Tags: {name}", flush=True)
    except ClientError as exc:
        print(
            f"  跳过 Tags ({name}): {exc.response['Error']['Code']} — DynamoDB Local 不支持",
            flush=True,
        )


def create_all(client, specs: list[dict[str, Any]]) -> None:
    for spec in specs:
        name = spec["TableName"]
        if _table_exists(client, name):
            print(f"skip {name} (已存在)", flush=True)
            continue
        print(f"创建 {name} ...", flush=True)
        # 复制并去掉内部辅助字段再传给 boto3.
        api_spec = {k: v for k, v in spec.items() if not k.startswith("_")}
        try:
            client.create_table(**api_spec)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "ResourceInUseException":
                print(f"skip {name} (并发已建)", flush=True)
                continue
            raise
        _wait_active(client, name)
        if spec.get("_ttl_attr"):
            _try_enable_ttl(client, name, spec["_ttl_attr"])
        _try_apply_tags(client, name)
        print(f"OK  {name} created", flush=True)


def delete_all(client, specs: list[dict[str, Any]]) -> None:
    # 反向顺序删除, 与 sh 脚本保持一致.
    for spec in reversed(specs):
        name = spec["TableName"]
        if not _table_exists(client, name):
            print(f"skip {name} (不存在)", flush=True)
            continue
        print(f"删除 {name} ...", flush=True)
        client.delete_table(TableName=name)
        _wait_deleted(client, name)
        print(f"OK  {name} deleted", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delete",
        action="store_true",
        help="反向删除 5 张表 (默认: 创建)",
    )
    args = parser.parse_args()

    client = _make_client()
    specs = _table_specs(TABLE_PREFIX)

    print(f"[ddb-local-bootstrap] endpoint = {DDB_ENDPOINT_URL}", flush=True)
    print(f"[ddb-local-bootstrap] region   = {AWS_REGION}", flush=True)
    print(f"[ddb-local-bootstrap] prefix   = {TABLE_PREFIX}", flush=True)
    print(
        f"[ddb-local-bootstrap] 5 张表    = "
        + ", ".join(s["TableName"] for s in specs),
        flush=True,
    )
    print("", flush=True)

    if args.delete:
        delete_all(client, specs)
    else:
        create_all(client, specs)

    print("", flush=True)
    print("[ddb-local-bootstrap] 当前 endpoint 表清单:", flush=True)
    resp = client.list_tables()
    for t in resp.get("TableNames", []):
        if t.startswith(TABLE_PREFIX):
            print(f"  - {t}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
