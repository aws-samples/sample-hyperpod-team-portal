#!/usr/bin/env bash
# 本地 demo (非 CDK) 镜像在线构建资源手动建。幂等: 已存在则跳过/更新。
# 复用 A 阶段已建的 CodeBuild project(image-builder)/service role/S3 桶。
#
# 用法: AWS_PROFILE=my-profile ./deploy/local-image-build-setup.sh
set -euo pipefail
REGION=us-west-2
ACCT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="codebuild-src-$ACCT-$REGION"     # A 阶段已建, 复用
CB_ROLE=codebuild-image-builder-role     # A 阶段已建
POD_ROLE=platform-pod-role
PROJECT=image-builder                    # A 阶段已建
PREFIX=hypd-demo                       # = 后端 settings.ddb_table_prefix

echo ">> 1. DDB 表 ${PREFIX}-ImageBuilds"
aws dynamodb describe-table --table-name ${PREFIX}-ImageBuilds --region $REGION >/dev/null 2>&1 \
  || aws dynamodb create-table --table-name ${PREFIX}-ImageBuilds --region $REGION \
       --billing-mode PAY_PER_REQUEST \
       --attribute-definitions AttributeName=workspace_id,AttributeType=S AttributeName=sort_key,AttributeType=S \
       --key-schema AttributeName=workspace_id,KeyType=HASH AttributeName=sort_key,KeyType=RANGE >/dev/null
echo "   ok"

echo ">> 2. CodeBuild service role policy (push scope ${PREFIX}-ws-*; pull 放开 * 支持 FROM 官方镜像)"
python3 - "$ACCT" "$REGION" "$BUCKET" "$PREFIX" <<'PY'
import json, subprocess, sys
acct, region, bucket, prefix = sys.argv[1:5]
pol = {"Version": "2012-10-17", "Statement": [
  {"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
   "Resource": f"arn:aws:logs:{region}:{acct}:log-group:/aws/codebuild/*"},
  {"Effect": "Allow", "Action": ["s3:GetObject", "s3:GetObjectVersion"], "Resource": f"arn:aws:s3:::{bucket}/*"},
  {"Effect": "Allow", "Action": ["ecr:GetAuthorizationToken"], "Resource": "*"},
  # push: 严格 scope 到自账号 ws repo (镜像隔离)
  {"Effect": "Allow", "Action": ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer",
    "ecr:BatchGetImage", "ecr:PutImage", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
    "ecr:CompleteLayerUpload"],
   "Resource": [f"arn:aws:ecr:{region}:{acct}:repository/{prefix}-ws-*",
                f"arn:aws:ecr:{region}:{acct}:repository/codebuild-test"]},
  # pull: 放开到 * (FROM 任意官方/公共镜像 DLC/SageMaker 等; 实际可拉性由对方 repo policy 决定)
  {"Effect": "Allow", "Action": ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer",
    "ecr:BatchGetImage"], "Resource": "*"}]}
open("/tmp/cb-pol.json", "w").write(json.dumps(pol))
subprocess.run(["aws", "iam", "put-role-policy", "--role-name", "codebuild-image-builder-role",
  "--policy-name", "codebuild-image-builder-policy", "--policy-document", "file:///tmp/cb-pol.json"], check=True)
PY
echo "   ok"

echo ">> 3. platform-pod-role 加权 (codebuild/s3/passrole/ecr/logs)"
python3 - "$ACCT" "$REGION" "$BUCKET" <<'PY'
import json, subprocess, sys
acct, region, bucket = sys.argv[1:4]
pol = {"Version": "2012-10-17", "Statement": [
  {"Effect": "Allow", "Action": ["codebuild:StartBuild", "codebuild:BatchGetBuilds"],
   "Resource": f"arn:aws:codebuild:{region}:{acct}:project/image-builder"},
  {"Effect": "Allow", "Action": ["s3:PutObject"], "Resource": f"arn:aws:s3:::{bucket}/*"},
  {"Effect": "Allow", "Action": ["iam:PassRole"],
   "Resource": f"arn:aws:iam::{acct}:role/codebuild-image-builder-role"},
  {"Effect": "Allow", "Action": ["ecr:CreateRepository", "ecr:PutLifecyclePolicy", "ecr:DescribeRepositories"],
   "Resource": "*"},
  {"Effect": "Allow", "Action": ["logs:GetLogEvents"],
   "Resource": f"arn:aws:logs:{region}:{acct}:log-group:/aws/codebuild/*"}]}
open("/tmp/pod-cb-pol.json", "w").write(json.dumps(pol))
subprocess.run(["aws", "iam", "put-role-policy", "--role-name", "platform-pod-role",
  "--policy-name", "image-build-policy", "--policy-document", "file:///tmp/pod-cb-pol.json"], check=True)
PY
echo "   ok"

echo ">> 完成。确认本地 .env 有:"
echo "   CODEBUILD_PROJECT_NAME=image-builder"
echo "   IMAGE_BUILD_SOURCE_BUCKET=$BUCKET"
