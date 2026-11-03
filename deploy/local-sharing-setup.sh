#!/usr/bin/env bash
# demo 本地建 ResourceShares 表 (demo 非 CDK, 手动建)。幂等。
set -euo pipefail
PROFILE="${AWS_PROFILE:-my-profile}"
REGION="${AWS_REGION:-us-west-2}"
TABLE="hypd-demo-ResourceShares"

if aws dynamodb describe-table --table-name "$TABLE" --profile "$PROFILE" --region "$REGION" >/dev/null 2>&1; then
  echo "表 $TABLE 已存在, 跳过"
  exit 0
fi

aws dynamodb create-table \
  --table-name "$TABLE" \
  --attribute-definitions \
      AttributeName=workspace_id,AttributeType=S \
      AttributeName=share_key,AttributeType=S \
      AttributeName=target_username,AttributeType=S \
  --key-schema \
      AttributeName=workspace_id,KeyType=HASH \
      AttributeName=share_key,KeyType=RANGE \
  --global-secondary-indexes \
      'IndexName=target-username-index,KeySchema=[{AttributeName=target_username,KeyType=HASH},{AttributeName=workspace_id,KeyType=RANGE}],Projection={ProjectionType=ALL}' \
  --billing-mode PAY_PER_REQUEST \
  --profile "$PROFILE" --region "$REGION"

echo "已建表 $TABLE"
