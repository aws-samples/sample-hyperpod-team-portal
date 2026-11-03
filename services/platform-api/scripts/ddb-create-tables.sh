#!/usr/bin/env bash
# ============================================================
# ddb-create-tables.sh
# ------------------------------------------------------------
# 在 AWS 真实区域创建/删除 修订版定义的 5 张 DDB 表.
# 用法:
#   TABLE_PREFIX=hypd-prod AWS_REGION=us-west-2 ./ddb-create-tables.sh
#   TABLE_PREFIX=hypd-prod AWS_REGION=us-west-2 ./ddb-create-tables.sh delete
#
# 默认值:
#   TABLE_PREFIX = hypd-dev
#   AWS_REGION   = us-west-2
#
# 5 张表 (PAY_PER_REQUEST + PITR + AWS managed SSE):
#   - <prefix>-PlatformAdmins (username PK · 平台超级管理员标记)
#   - <prefix>-Workspaces (workspace_id PK · 无 owner)
#   - <prefix>-WorkspaceMembers (workspace_id PK + username SK)
#   - <prefix>-ResourceIndex (workspace_id PK + resource_key SK)
#   - <prefix>-AuditLog (scope_key PK + event_key SK · TTL on expire_at)
#
# 修订记录:
#   - 2026-05-20: 删 Users 表; PlatformAdmins PK 改 username (从 email);
#     WorkspaceMembers SK 改 username (从 user_id UUID); Workspaces 删
#     owner_user_id 字段 + owner-index GSI.
#
# 兼容: macOS bash 3.2 / Linux bash 4+
# ============================================================
set -euo pipefail

TABLE_PREFIX="${TABLE_PREFIX:-hypd-dev}"
AWS_REGION="${AWS_REGION:-us-west-2}"
ACTION="${1:-create}"

WORKSPACES_TABLE="${TABLE_PREFIX}-Workspaces"
MEMBERS_TABLE="${TABLE_PREFIX}-WorkspaceMembers"
RINDEX_TABLE="${TABLE_PREFIX}-ResourceIndex"
AUDIT_TABLE="${TABLE_PREFIX}-AuditLog"
PLATFORM_ADMINS_TABLE="${TABLE_PREFIX}-PlatformAdmins"
MOUNT_PERMS_TABLE="${TABLE_PREFIX}-MountPermissions"
RES_TPL_TABLE="${TABLE_PREFIX}-ResourceTemplates"
API_TOKENS_TABLE="${TABLE_PREFIX}-ApiTokens"

# 反向删除顺序 (8 张表彼此无外键, 顺序仅影响日志可读)
ALL_TABLES_CREATE_ORDER=(
  "${PLATFORM_ADMINS_TABLE}"
  "${WORKSPACES_TABLE}"
  "${MEMBERS_TABLE}"
  "${RINDEX_TABLE}"
  "${AUDIT_TABLE}"
  "${MOUNT_PERMS_TABLE}"
  "${RES_TPL_TABLE}"
  "${API_TOKENS_TABLE}"
)
ALL_TABLES_DELETE_ORDER=(
  "${API_TOKENS_TABLE}"
  "${RES_TPL_TABLE}"
  "${MOUNT_PERMS_TABLE}"
  "${AUDIT_TABLE}"
  "${RINDEX_TABLE}"
  "${MEMBERS_TABLE}"
  "${WORKSPACES_TABLE}"
  "${PLATFORM_ADMINS_TABLE}"
)

# ---------- 通用工具函数 ----------

log() {
  printf '[ddb-bootstrap] %s\n' "$*"
}

aws_ddb() {
  aws dynamodb --region "${AWS_REGION}" "$@"
}

table_exists() {
  local name="$1"
  aws_ddb describe-table --table-name "${name}" >/dev/null 2>&1
}

wait_active() {
  local name="$1"
  log "  等待 ${name} 进入 ACTIVE ..."
  aws_ddb wait table-exists --table-name "${name}"
}

wait_deleted() {
  local name="$1"
  log "  等待 ${name} 删除完成 ..."
  aws_ddb wait table-not-exists --table-name "${name}"
}

enable_pitr() {
  local name="$1"
  log "  启用 PITR: ${name}"
  local i=0
  while [ $i -lt 6 ]; do
    if aws_ddb update-continuous-backups \
        --table-name "${name}" \
        --point-in-time-recovery-specification "PointInTimeRecoveryEnabled=true" \
        >/dev/null 2>&1; then
      return 0
    fi
    i=$((i + 1))
    sleep 5
    log "    PITR retry ${i}/6 for ${name}"
  done
  log "  ! PITR enable failed for ${name} after 6 retries (continuing)"
  return 0
}

apply_tags() {
  local name="$1"
  log "  打 Tags: ${name}"
  local arn
  arn="$(aws_ddb describe-table --table-name "${name}" --query 'Table.TableArn' --output text)"
  aws_ddb tag-resource \
    --resource-arn "${arn}" \
    --tags \
      Key=Project,Value=hyperpod-platform \
      Key=ManagedBy,Value=cli-bootstrap \
      Key=Component,Value=platform-api \
    >/dev/null
}

enable_ttl() {
  local name="$1"
  local attr="$2"
  log "  启用 TTL: ${name} (attr=${attr})"
  aws_ddb update-time-to-live \
    --table-name "${name}" \
    --time-to-live-specification "Enabled=true,AttributeName=${attr}" \
    >/dev/null
}

# ---------- 5 张表的 JSON 定义 ----------
# 注意:
# - 用 stdin <<EOF 而不是命令行 --attribute-definitions 等长串, 避免转义错误.
# - 每张表 JSON 自成完整体, 与 aws cli v2 create-table --cli-input-json 兼容.

create_workspaces_table() {
  local name="${WORKSPACES_TABLE}"
  if table_exists "${name}"; then
    log "skip ${name} (已存在)"
    return 0
  fi
  log "创建 ${name} ..."
  aws_ddb create-table --cli-input-json "$(cat <<EOF
{
  "TableName": "${name}",
  "BillingMode": "PAY_PER_REQUEST",
  "AttributeDefinitions": [
    { "AttributeName": "workspace_id",      "AttributeType": "S" },
    { "AttributeName": "compute_quota_id",  "AttributeType": "S" }
  ],
  "KeySchema": [
    { "AttributeName": "workspace_id", "KeyType": "HASH" }
  ],
  "GlobalSecondaryIndexes": [
    {
      "IndexName": "compute_quota_id-index",
      "KeySchema": [
        { "AttributeName": "compute_quota_id", "KeyType": "HASH" }
      ],
      "Projection": { "ProjectionType": "ALL" }
    }
  ],
  "SSESpecification": {
    "Enabled": true,
    "SSEType": "KMS"
  }
}
EOF
)" >/dev/null
  wait_active "${name}"
  enable_pitr "${name}"
  apply_tags "${name}"
  log "✓ ${name} created"
}

create_members_table() {
  local name="${MEMBERS_TABLE}"
  if table_exists "${name}"; then
    log "skip ${name} (已存在)"
    return 0
  fi
  log "创建 ${name} ..."
  aws_ddb create-table --cli-input-json "$(cat <<EOF
{
  "TableName": "${name}",
  "BillingMode": "PAY_PER_REQUEST",
  "AttributeDefinitions": [
    { "AttributeName": "workspace_id", "AttributeType": "S" },
    { "AttributeName": "username",     "AttributeType": "S" }
  ],
  "KeySchema": [
    { "AttributeName": "workspace_id", "KeyType": "HASH" },
    { "AttributeName": "username",     "KeyType": "RANGE" }
  ],
  "GlobalSecondaryIndexes": [
    {
      "IndexName": "username-index",
      "KeySchema": [
        { "AttributeName": "username",     "KeyType": "HASH" },
        { "AttributeName": "workspace_id", "KeyType": "RANGE" }
      ],
      "Projection": { "ProjectionType": "ALL" }
    }
  ],
  "SSESpecification": {
    "Enabled": true,
    "SSEType": "KMS"
  }
}
EOF
)" >/dev/null
  wait_active "${name}"
  enable_pitr "${name}"
  apply_tags "${name}"
  log "✓ ${name} created"
}

create_mount_perms_table() {
  local name="${MOUNT_PERMS_TABLE}"
  if table_exists "${name}"; then
    log "skip ${name} (已存在)"
    return 0
  fi
  log "创建 ${name} ..."
  aws_ddb create-table --cli-input-json "$(cat <<EOF
{
  "TableName": "${name}",
  "BillingMode": "PAY_PER_REQUEST",
  "AttributeDefinitions": [
    { "AttributeName": "workspace_id", "AttributeType": "S" },
    { "AttributeName": "perm_key",     "AttributeType": "S" },
    { "AttributeName": "username",     "AttributeType": "S" }
  ],
  "KeySchema": [
    { "AttributeName": "workspace_id", "KeyType": "HASH" },
    { "AttributeName": "perm_key",     "KeyType": "RANGE" }
  ],
  "GlobalSecondaryIndexes": [
    {
      "IndexName": "username-index",
      "KeySchema": [
        { "AttributeName": "username",     "KeyType": "HASH" },
        { "AttributeName": "workspace_id", "KeyType": "RANGE" }
      ],
      "Projection": { "ProjectionType": "ALL" }
    }
  ],
  "SSESpecification": {
    "Enabled": true,
    "SSEType": "KMS"
  }
}
EOF
)" >/dev/null
  wait_active "${name}"
  enable_pitr "${name}"
  apply_tags "${name}"
  log "✓ ${name} created"
}

create_res_tpl_table() {
  local name="${RES_TPL_TABLE}"
  if table_exists "${name}"; then
    log "skip ${name} (已存在)"
    return 0
  fi
  log "创建 ${name} ..."
  aws_ddb create-table --cli-input-json "$(cat <<EOF
{
  "TableName": "${name}",
  "BillingMode": "PAY_PER_REQUEST",
  "AttributeDefinitions": [
    { "AttributeName": "workspace_id", "AttributeType": "S" },
    { "AttributeName": "sort_key",     "AttributeType": "S" }
  ],
  "KeySchema": [
    { "AttributeName": "workspace_id", "KeyType": "HASH" },
    { "AttributeName": "sort_key",     "KeyType": "RANGE" }
  ],
  "SSESpecification": {
    "Enabled": true,
    "SSEType": "KMS"
  }
}
EOF
)" >/dev/null
  wait_active "${name}"
  enable_pitr "${name}"
  apply_tags "${name}"
  log "✓ ${name} created"
}

create_rindex_table() {
  local name="${RINDEX_TABLE}"
  if table_exists "${name}"; then
    log "skip ${name} (已存在)"
    return 0
  fi
  log "创建 ${name} ..."
  aws_ddb create-table --cli-input-json "$(cat <<EOF
{
  "TableName": "${name}",
  "BillingMode": "PAY_PER_REQUEST",
  "AttributeDefinitions": [
    { "AttributeName": "workspace_id",     "AttributeType": "S" },
    { "AttributeName": "resource_key",     "AttributeType": "S" },
    { "AttributeName": "creator_user_id",  "AttributeType": "S" },
    { "AttributeName": "resource_type",    "AttributeType": "S" },
    { "AttributeName": "created_at",       "AttributeType": "S" },
    { "AttributeName": "active_ws",        "AttributeType": "S" }
  ],
  "KeySchema": [
    { "AttributeName": "workspace_id", "KeyType": "HASH" },
    { "AttributeName": "resource_key", "KeyType": "RANGE" }
  ],
  "GlobalSecondaryIndexes": [
    {
      "IndexName": "creator-index",
      "KeySchema": [
        { "AttributeName": "creator_user_id", "KeyType": "HASH" },
        { "AttributeName": "created_at",      "KeyType": "RANGE" }
      ],
      "Projection": { "ProjectionType": "ALL" }
    },
    {
      "IndexName": "type-time-index",
      "KeySchema": [
        { "AttributeName": "resource_type", "KeyType": "HASH" },
        { "AttributeName": "created_at",    "KeyType": "RANGE" }
      ],
      "Projection": { "ProjectionType": "ALL" }
    },
    {
      "IndexName": "active-index",
      "KeySchema": [
        { "AttributeName": "active_ws",  "KeyType": "HASH" },
        { "AttributeName": "created_at", "KeyType": "RANGE" }
      ],
      "Projection": { "ProjectionType": "ALL" }
    }
  ],
  "SSESpecification": {
    "Enabled": true,
    "SSEType": "KMS"
  }
}
EOF
)" >/dev/null
  wait_active "${name}"
  enable_pitr "${name}"
  apply_tags "${name}"
  log "✓ ${name} created"
}

create_audit_table() {
  local name="${AUDIT_TABLE}"
  if table_exists "${name}"; then
    log "skip ${name} (已存在)"
    return 0
  fi
  log "创建 ${name} ..."
  aws_ddb create-table --cli-input-json "$(cat <<EOF
{
  "TableName": "${name}",
  "BillingMode": "PAY_PER_REQUEST",
  "AttributeDefinitions": [
    { "AttributeName": "scope_key",       "AttributeType": "S" },
    { "AttributeName": "event_key",       "AttributeType": "S" },
    { "AttributeName": "actor_user_id",   "AttributeType": "S" },
    { "AttributeName": "created_at",      "AttributeType": "S" }
  ],
  "KeySchema": [
    { "AttributeName": "scope_key", "KeyType": "HASH" },
    { "AttributeName": "event_key", "KeyType": "RANGE" }
  ],
  "GlobalSecondaryIndexes": [
    {
      "IndexName": "actor-index",
      "KeySchema": [
        { "AttributeName": "actor_user_id", "KeyType": "HASH" },
        { "AttributeName": "created_at",    "KeyType": "RANGE" }
      ],
      "Projection": { "ProjectionType": "ALL" }
    }
  ],
  "SSESpecification": {
    "Enabled": true,
    "SSEType": "KMS"
  }
}
EOF
)" >/dev/null
  wait_active "${name}"
  enable_pitr "${name}"
  enable_ttl "${name}" "expire_at"
  apply_tags "${name}"
  log "✓ ${name} created"
}

create_platform_admins_table() {
  local name="${PLATFORM_ADMINS_TABLE}"
  if table_exists "${name}"; then
    log "skip ${name} (已存在)"
    return 0
  fi
  log "创建 ${name} ..."
  aws_ddb create-table --cli-input-json "$(cat <<EOF
{
  "TableName": "${name}",
  "BillingMode": "PAY_PER_REQUEST",
  "AttributeDefinitions": [
    { "AttributeName": "username", "AttributeType": "S" }
  ],
  "KeySchema": [
    { "AttributeName": "username", "KeyType": "HASH" }
  ],
  "SSESpecification": {
    "Enabled": true,
    "SSEType": "KMS"
  }
}
EOF
)" >/dev/null
  wait_active "${name}"
  enable_pitr "${name}"
  apply_tags "${name}"
  log "✓ ${name} created"
}

create_api_tokens_table() {
  local name="${API_TOKENS_TABLE}"
  if table_exists "${name}"; then
    log "skip ${name} (已存在)"
    return 0
  fi
  log "创建 ${name} ..."
  aws_ddb create-table --cli-input-json "$(cat <<EOF
{
  "TableName": "${name}",
  "BillingMode": "PAY_PER_REQUEST",
  "AttributeDefinitions": [
    { "AttributeName": "username",   "AttributeType": "S" },
    { "AttributeName": "token_hash", "AttributeType": "S" }
  ],
  "KeySchema": [
    { "AttributeName": "username", "KeyType": "HASH" }
  ],
  "GlobalSecondaryIndexes": [
    {
      "IndexName": "token_hash-index",
      "KeySchema": [
        { "AttributeName": "token_hash", "KeyType": "HASH" }
      ],
      "Projection": { "ProjectionType": "ALL" }
    }
  ],
  "SSESpecification": {
    "Enabled": true,
    "SSEType": "KMS"
  }
}
EOF
)" >/dev/null
  wait_active "${name}"
  enable_pitr "${name}"
  apply_tags "${name}"
  log "✓ ${name} created"
}

# ---------- 删除 ----------

delete_table() {
  local name="$1"
  if ! table_exists "${name}"; then
    log "skip ${name} (不存在)"
    return 0
  fi
  log "删除 ${name} ..."
  aws_ddb delete-table --table-name "${name}" >/dev/null
  wait_deleted "${name}"
  log "✓ ${name} deleted"
}

# ---------- 入口 ----------

main_create() {
  log "Region:       ${AWS_REGION}"
  log "Table prefix: ${TABLE_PREFIX}"
  log "目标 ${#ALL_TABLES_CREATE_ORDER[@]} 张表: ${ALL_TABLES_CREATE_ORDER[*]}"
  echo
  create_platform_admins_table
  create_workspaces_table
  create_members_table
  create_rindex_table
  create_audit_table
  create_mount_perms_table
  create_res_tpl_table
  create_api_tokens_table
  echo
  log "全部完成. 当前区域 DDB 表清单:"
  aws_ddb list-tables --query 'TableNames' --output text | tr '\t' '\n' | grep "^${TABLE_PREFIX}-" || true
}

main_delete() {
  log "Region:       ${AWS_REGION}"
  log "Table prefix: ${TABLE_PREFIX}"
  log "反向删除 ${#ALL_TABLES_DELETE_ORDER[@]} 张表 ..."
  echo
  for t in "${ALL_TABLES_DELETE_ORDER[@]}"; do
    delete_table "${t}"
  done
  echo
  log "全部删除完成."
}

case "${ACTION}" in
  create)
    main_create
    ;;
  delete)
    main_delete
    ;;
  *)
    echo "Usage: $0 [create|delete]" >&2
    exit 2
    ;;
esac
