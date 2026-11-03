"""DynamoDB low-level adapters.

模块边界:
    - client.py    aioboto3 lazy singleton (resource + client)
    - tables.py    5 张表 + GSI 名常量 (集中, 改一处全平台跟随)
    - base.py      put/get/query/update/delete 通用 helper (Repository 复用)

业务层 (app.repositories.*) 直接 import 这个包.
不要在业务模块里直接 boto3.client('dynamodb')—— 必须走 client.get_ddb_resource().
"""
