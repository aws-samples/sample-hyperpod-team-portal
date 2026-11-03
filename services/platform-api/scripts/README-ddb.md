# DDB 5 张表 bootstrap 脚本

替代原 RDS + Redis 元数据层. 脚本仅用于开发/测试期, 生产环境后续统一上 CDK.

## 5 张表

| 表 | 用途 |
|---|---|
| Users | Cognito 之外的极少补充字段 (last_login + uid/gid) |
| Workspaces | ComputeQuota 之外的 display_name / owner / metadata |
| WorkspaceMembers | workspace ↔ user 角色关系 (AWS 无对应抽象) |
| ResourceIndex | 跨 ws 跨 user 的资源列表索引 (详情走 K8s CR) |
| AuditLog | 操作历史 + actor 兜底, TTL 自动清理 (expire_at) |

## 本地 (DynamoDB Local)

```bash
# 1) 启 DynamoDB Local (端口 8000)
docker run -d --name ddb-local -p 8000:8000 amazon/dynamodb-local:2.5.4

# 2) 建 5 张表 (默认前缀 hypd-local-)
python ddb-local-bootstrap.py

# 3) 删表
python ddb-local-bootstrap.py --delete

# 自定义前缀 / endpoint:
TABLE_PREFIX=hypd-tmp- DDB_ENDPOINT_URL=http://localhost:8000 \
    python ddb-local-bootstrap.py
```

依赖: `boto3` (platform-api pyproject 已声明). 不依赖 app 模块, 可独立跑.

## 生产 (真实 AWS)

```bash
# 默认 TABLE_PREFIX=hypd-dev, AWS_REGION=us-west-2
AWS_PROFILE=hyperpod-dev TABLE_PREFIX=hypd-dev AWS_REGION=us-west-2 \
    ./ddb-create-tables.sh

# 反向删除
AWS_PROFILE=hyperpod-dev TABLE_PREFIX=hypd-dev AWS_REGION=us-west-2 \
    ./ddb-create-tables.sh delete
```

脚本会自动: create-table → 等 ACTIVE → 启 PITR → 启 TTL (仅 AuditLog) → 打 Tags
(`Project=hyperpod-platform`, `ManagedBy=cli-bootstrap`, `Component=platform-api`).
已存在的表会跳过, 不会破坏数据.

## 检查 / 排错

```bash
# 列表
aws dynamodb list-tables --region us-west-2 \
  --query 'TableNames[?starts_with(@,`hypd-dev-`)]'

# 查表详情
aws dynamodb describe-table --table-name hypd-dev-Workspaces --region us-west-2

# 查 PITR
aws dynamodb describe-continuous-backups --table-name hypd-dev-AuditLog --region us-west-2

# 查 TTL
aws dynamodb describe-time-to-live --table-name hypd-dev-AuditLog --region us-west-2
```

## 运行模式备忘

| 维度 | 本地 | 真实 AWS |
|---|---|---|
| 入口 | `ddb-local-bootstrap.py` | `ddb-create-tables.sh` |
| 表前缀 | `hypd-local-` | `hypd-dev` (按环境改) |
| PITR | 不支持 (DDB Local 限制) | 启用 |
| TTL | API 可调用, 真实清理依实现 | 启用 (AuditLog.expire_at) |
| Tags | 跳过 (DDB Local 不支持) | 三个 tag 全打 |
| 凭证 | dummy | AWS_PROFILE / 环境变量 |

后续接入 CDK 时, 把 `ddb-create-tables.sh` 中的 5 段 JSON 直接迁成 CDK
`Table` construct + GSI 数组即可, schema 1:1 对应.
