#!/usr/bin/env bash
#
# 平台部署 orchestrator — 把 CDK + 之后到 Cognito 回填之前的步骤串起来:
#   cdk    → cdk deploy {project}-platform-stack (建平台集群 + DDB/Cognito/ECR/IAM + 跨集群 access entry)
#            当 cdk.json 的 logArchiveMode=cost|query 时, 顺带部署 {project}-log-archive-stack (日志备份 → S3)
#   init   → cluster-init.sh   (kubeconfig + 自身 access entry + ALB controller + WorkloadPriorityClass)
#   build  → build-push.sh     (build + push 3 镜像 platform-api / platform-controller(Go, ECR repo 复用 platform-worker) / frontend)
#   apply  → render-and-apply.sh (渲染 manifest + 部署到平台集群)
#
# ⚠️ cdk 不在默认步骤里 (默认只跑 init build apply)。原因:
#   - cdk deploy 是最重 / 最常要看 diff 重来的一步, 留人工检查点更稳
#   - 放进流程必须带 --require-approval never (自动批准 IAM 变更), 本脚本 cdk 步骤已带,
#     仅当你显式写 cdk 才会触发, 知情使用
#
# 不含 (故意留外面):
#   - cluster-prereq.sh   → 业务集群 Prerequisites, 在 cdk 之前, 单独跑
#   - cognito-callback.sh → 回填 callback, 留人工 (URL 因场景而异, 见脚本注释)
#
# init/build/apply 都自动从 infrastructure/cdk.json + CDK Output 读参, 无需手贴变量。
# 任一步失败立即停 (set -e), 不会带着坏状态往下跑。
#
# 用法:
#   TAG=v2 ./deploy/deploy-platform.sh                  # 默认 (init → build → apply), 假设 cdk 已手动跑过
#   TAG=v2 ./deploy/deploy-platform.sh cdk init build apply   # 含 cdk 的全自动 (会自动批准 IAM 变更)
#   TAG=v2 ./deploy/deploy-platform.sh apply            # 改了 manifest, 只重 apply
#   ./deploy/deploy-platform.sh cdk                     # 只 cdk/init (不含 build/apply) 无需 TAG
#
# ⚠️ 含 build/apply 步骤时 TAG 必填 (无默认 v1): tag 每次累加, 默认 v1 会回退线上镜像。
#
# 前提: docker 在跑; aws/kubectl/helm/cdk 可用; 凭证就绪 (如 export AWS_PROFILE=xxx)。
#
# 部署完后还要做 (本脚本不含):
#   - ./deploy/cognito-callback.sh   回填 Cognito callback URL
#   - 跨集群安全组放行 443 / 8888 (见 deployment-guideline.md "跨集群安全组放行")
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CDK_JSON="$ROOT/infrastructure/cdk.json"

ctx() { python3 -c "import json,sys; print(json.load(open('$CDK_JSON'))['context'].get('$1',''))"; }

STEPS=("$@")
[ ${#STEPS[@]} -eq 0 ] && STEPS=(init build apply)

# 含 build/apply 步骤时 TAG 必填 (无默认 v1, 防镜像回退); 纯 cdk/init 不需要。
case " ${STEPS[*]} " in
  *" build "*|*" apply "*)
    : "${TAG:?需要 TAG (镜像 tag, 如 TAG=v49); build/apply 步骤无默认值防回退}" ;;
esac

echo "============================================================"
echo ">> 平台部署 orchestrator  steps=${STEPS[*]}  TAG=${TAG:-<未设/本次无 build|apply>}"
echo "============================================================"

for step in "${STEPS[@]}"; do
  echo
  case "$step" in
    cdk)
      echo ">>> [cdk] cdk deploy (⚠️ --require-approval never, 自动批准 IAM 变更)"
      PROJECT="$(ctx projectName)"
      STACKS=("${PROJECT}-platform-stack")
      # logArchiveMode 为 cost/query 时, 顺带部署日志备份栈 (log group subscription → Firehose → S3)
      LOG_ARCHIVE_MODE="$(ctx logArchiveMode)"
      if [ "$LOG_ARCHIVE_MODE" = "cost" ] || [ "$LOG_ARCHIVE_MODE" = "query" ]; then
        echo "    ↳ logArchiveMode=$LOG_ARCHIVE_MODE, 一并部署 ${PROJECT}-log-archive-stack"
        STACKS+=("${PROJECT}-log-archive-stack")
      fi
      ( cd "$ROOT/infrastructure" && cdk deploy "${STACKS[@]}" --require-approval never )
      ;;
    init)
      echo ">>> [init] 集群初始化 (cluster-init.sh)"
      "$SCRIPT_DIR/cluster-init.sh"
      ;;
    build)
      echo ">>> [build] build + push 3 镜像 (build-push.sh, TAG=$TAG)"
      "$SCRIPT_DIR/build-push.sh"
      ;;
    apply)
      echo ">>> [apply] 渲染 + 部署到平台集群 (render-and-apply.sh, TAG=$TAG)"
      "$SCRIPT_DIR/render-and-apply.sh"
      ;;
    *)
      echo "❌ 未知步骤 '$step' (可选: cdk | init | build | apply)" >&2
      exit 1
      ;;
  esac
  echo ">>> [$step] ✓ 完成"
done

echo
echo "============================================================"
echo ">> 全部步骤完成。接下来手动做:"
echo "   1. ./deploy/cognito-callback.sh   回填 Cognito callback URL"
echo "   2. 跨集群安全组放行 443/8888 (见 deployment-guideline.md)"
echo "============================================================"
