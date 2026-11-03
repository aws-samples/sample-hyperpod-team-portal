#!/usr/bin/env bash
#
# Build + Push 平台 3 个镜像到 ECR (platform-api / platform-worker / frontend).
# 自动从 infrastructure/cdk.json 读 account/region/projectName, 不用手贴变量。
#
# 用法:
#   TAG=v2 ./deploy/build-push.sh              # build+push 全部 3 个 (TAG 必填)
#   TAG=v2 ./deploy/build-push.sh api          # 只 build+push 后端 (api|worker|frontend)
#   TAG=v2 ./deploy/build-push.sh api worker   # 指定多个
#
# ⚠️ TAG 必填 (无默认): tag 每次累加, 默认 v1 会覆盖最早镜像 → apply 时回退线上。
#
# 前提: docker 在跑; AWS 凭证可用 (ecr / ecr-public 登录权限)。
# mac arm 必须 --platform linux/amd64 (脚本已带)。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CDK_JSON="$ROOT/infrastructure/cdk.json"
# TAG 必填 (无默认 v1): 防止覆盖最早镜像导致 apply 回退。
: "${TAG:?需要 TAG (镜像 tag, 如 TAG=v49); 无默认值防回退}"

ctx() { python3 -c "import json,sys; print(json.load(open('$CDK_JSON'))['context'].get('$1',''))"; }
PROJECT="$(ctx projectName)"
ACCOUNT="$(ctx account)"
REGION="$(ctx region)"
ECR="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

# 要 build 哪些 (默认全部)
TARGETS=("$@")
[ ${#TARGETS[@]} -eq 0 ] && TARGETS=(api worker frontend)

echo ">> ECR=$ECR  PROJECT=$PROJECT  TAG=$TAG  targets=${TARGETS[*]}"

# ---- 登录 ECR ----
echo ">> 登录 public ECR (拉 base 镜像; 固定 us-east-1)"
aws ecr-public get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin public.ecr.aws >/dev/null
echo ">> 登录私有 ECR ($REGION)"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$ECR" >/dev/null

build_one() {
  case "$1" in
    api)
      echo ">> [api] build + push"
      docker build --platform linux/amd64 \
        -t "$ECR/$PROJECT-platform-api:$TAG" "$ROOT/services/platform-api"
      docker push "$ECR/$PROJECT-platform-api:$TAG"
      ;;
    worker)
      # platform-controller (Go) 取代旧 Python worker。ECR repo 仍复用
      # platform-worker (仓库只是名字, 塞 Go 镜像; CDK ECR 不动)。
      # build context = services/platform-controller/ (Go module 自包含, 不依赖 platform-api)。
      echo ">> [worker→controller] build + push (Go, context=services/platform-controller/)"
      docker build --platform linux/amd64 \
        -t "$ECR/$PROJECT-platform-worker:$TAG" "$ROOT/services/platform-controller"
      docker push "$ECR/$PROJECT-platform-worker:$TAG"
      ;;
    frontend)
      echo ">> [frontend] build + push"
      docker build --platform linux/amd64 \
        -t "$ECR/$PROJECT-frontend:$TAG" "$ROOT/frontend"
      docker push "$ECR/$PROJECT-frontend:$TAG"
      ;;
    *)
      echo "❌ 未知 target: $1 (可选 api|worker|frontend)" >&2; exit 1 ;;
  esac
}

for t in "${TARGETS[@]}"; do build_one "$t"; done

echo ">> 完成. 镜像 tag=$TAG 已推到 $ECR"
echo "   接下来: ./deploy/render-and-apply.sh  (或 rollout restart 拉新镜像)"
