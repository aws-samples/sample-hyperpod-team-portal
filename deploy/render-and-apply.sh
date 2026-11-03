#!/usr/bin/env bash
#
# 渲染 deploy/k8s/*.yaml 占位符并部署平台前后端到平台 EKS 集群.
# 值来源: CDK Stack Output (DDB/Cognito/role) + cdk.json context (集群名/资源 id)。
#
# 自动判定单/跨集群:
#   - 跨集群 (平台集群 != 业务集群): apply 到平台集群, 后端 env 注入
#     CROSS_CLUSTER_MODE/KUBE_CONTEXT 指向业务集群, 并自动建 cross-cluster-kubeconfig secret
#   - 单集群 (两者同名): apply 到当前 context, 不注入跨集群 env
#
# 用法:
#   TAG=v2 ./deploy/render-and-apply.sh             # 渲染 + apply (TAG 必填)
#   TAG=v2 ./deploy/render-and-apply.sh --dry-run   # 只渲染打印, 不 apply
#   SKIP_KUBECONFIG_SECRET=1 TAG=v2 ./deploy/...     # 跳过自动建 secret (已手动建好时)
#
# ⚠️ TAG 必填 (无默认): 每次部署 tag 累加, 默认 v1 会把线上回退到最早镜像。
#
# 前提: CDK 已 deploy; 镜像已 build+push (build-push.sh); 平台集群已 update-kubeconfig --alias。
set -euo pipefail

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CDK_JSON="$ROOT/infrastructure/cdk.json"
K8S_DIR="$ROOT/deploy/k8s"
# TAG 必填 (无默认 v1): tag 每次部署累加, 默认 v1 会把线上镜像回退到最早版本。
: "${TAG:?需要 TAG (镜像 tag, 如 TAG=v49); 无默认值防回退}"

# ---- 从 cdk.json context 读 ----
ctx() { python3 -c "import json,sys; print(json.load(open('$CDK_JSON'))['context'].get('$1',''))"; }

PROJECT="$(ctx projectName)"
STACK="${STACK:-${PROJECT}-platform-stack}"   # 跟 app.py 的 stack 命名一致
ACCOUNT="$(ctx account)"
REGION="$(ctx region)"
BUSINESS_CLUSTER="$(ctx businessClusterName)"
HYPERPOD_CLUSTER="$(ctx hyperpodClusterName)"
# HyperPod 集群 CloudWatch 日志组全名 (后端 LOG_GROUP_NAME, 日志快路径)。
LOG_GROUP_NAME="$(ctx hyperpodClusterLogGroupName)"
FSX_FILESYSTEMS="$(ctx platformFsxFilesystems)"   # 多 FSx: 逗号分隔 fs-id
AMP_WS_ID="$(ctx ampWorkspaceId)"
IDC_STORE_ID="$(ctx idcIdentityStoreId)"
IDC_REGION="$(ctx idcRegion)"
# 跨账号 IdC: 管理账号只读角色 ARN. 同账号留空 (走本地 Pod Identity 凭证)。
IDC_ASSUME_ROLE_ARN="$(ctx idcAssumeRoleArn)"
S3_BUCKETS="$(ctx platformS3Buckets)"
PLATFORM_NS="$(ctx platformNamespace)"
ALB_CERT_ARN="$(ctx albCertificateArn)"

# 平台集群 / 业务集群恒定分开 (跨集群部署):
#   - 后端 EKS_CLUSTER_NAME / KUBE_CONTEXT 指【业务集群】(开发机/FSx 在那, 跨集群访问)
#   - manifest apply 目标 = 【平台集群】(前后端 pod 跑这里, 从 CDK Output 取真名)
CROSS_CLUSTER_MODE="true"                   # 恒跨集群; 后端 env + 建 cross-cluster-kubeconfig secret 用
EKS_CLUSTER="$BUSINESS_CLUSTER"
KUBE_CONTEXT="$BUSINESS_CLUSTER"            # kubeconfig 里业务集群的 context 名
KUBECONFIG_PATH="/etc/business-kube/config"

# 一次拉全部 CDK Output 缓存 (避免每个值都 describe-stacks, 跨境慢). key<TAB>value。
_OUT_CACHE=""
out() {
  if [ -z "$_OUT_CACHE" ]; then
    _OUT_CACHE="$(aws cloudformation describe-stacks --stack-name "$STACK" \
      --region "$REGION" \
      --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" \
      --output text 2>/dev/null)"
  fi
  awk -v k="$1" 'BEGIN{FS="\t"} $1==k && !seen {seen=1; print substr($0, index($0,"\t")+1)}' \
    <<<"$_OUT_CACHE"
}

echo ">> 读取 CDK Output (stack=$STACK, region=$REGION)..."
DDB_PREFIX="$(out DdbTablePrefix)"
POD_ROLE_ARN="$(out PlatformPodRoleArn)"
SSM_ROLE_ARN="$(out SsmManagedNodeRoleArn)"
# 镜像在线构建 (CodeBuild): 后端 CODEBUILD_PROJECT_NAME / IMAGE_BUILD_SOURCE_BUCKET,
# 两者非空才启用构建。来自 ImageBuildConstruct 的 Output。
CODEBUILD_PROJECT="$(out CodeBuildProjectName)"
IMAGE_BUILD_BUCKET="$(out ImageBuildSourceBucket)"
# 平台集群名 = CDK Output 的真名 (apply manifest 目标 context); 不自己拼。
PLATFORM_CLUSTER="$(out PlatformClusterName)"
APPLY_CONTEXT="${PLATFORM_CONTEXT:-$PLATFORM_CLUSTER}"

# Cognito: 全部从 CDK Output 取 (CDK 自建的 pool)。region 用部署 region。
COGNITO_POOL_ID="$(out CognitoUserPoolId)"
COGNITO_CLIENT_ID="$(out CognitoClientId)"
COGNITO_DOMAIN="$(out CognitoDomain)"
COGNITO_REGION="$REGION"
# IdC (store id + region) 已从 cdk.json 取 (ctx idcIdentityStoreId / idcRegion, 见上方)。
# PKCE redirect_uri: 必须与 Cognito App Client 注册的 callback 精确一致.
# 默认从 cdk.json albDomainName 拼 https://<域名>/auth/callback (公网域名访问);
# albDomainName 为空时回退 localhost:8080 (SSM 隧道联调). 可设环境变量 LOCAL_CALLBACK_URL 覆盖.
ALB_DOMAIN="$(ctx albDomainName)"
if [ -n "${LOCAL_CALLBACK_URL:-}" ]; then
  :  # 显式覆盖, 原样用
elif [ -n "$ALB_DOMAIN" ]; then
  LOCAL_CALLBACK_URL="https://${ALB_DOMAIN}/auth/callback"
else
  LOCAL_CALLBACK_URL="http://localhost:8080/auth/callback"
fi

if [ -z "$DDB_PREFIX" ] || [ -z "$COGNITO_POOL_ID" ]; then
  echo "❌ 取不到 DDB/Cognito 配置 — 确认 $STACK 已 deploy (CDK Output 为空?)" >&2
  exit 1
fi
if [ -z "$PLATFORM_CLUSTER" ]; then
  echo "❌ 取不到 PlatformClusterName Output — 确认 $STACK 已 deploy" >&2
  exit 1
fi

ECR="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

echo ">> 变量汇总:"
echo "   PROJECT=$PROJECT  TAG=$TAG  REGION=$REGION"
echo "   平台集群=$PLATFORM_CLUSTER  业务集群=$BUSINESS_CLUSTER"
echo "   apply 到 context=$APPLY_CONTEXT  后端 KUBE_CONTEXT=$KUBE_CONTEXT"
echo "   image(api)=$ECR/$PROJECT-platform-api:$TAG  DDB_PREFIX=$DDB_PREFIX"

# ---- 渲染函数 ----
render() {
  sed -e "s|<ACCOUNT>|$ACCOUNT|g" \
      -e "s|<REGION>|$REGION|g" \
      -e "s|<TAG>|$TAG|g" \
      -e "s|<PROJECT>|$PROJECT|g" \
      -e "s|<DDB_PREFIX>|$DDB_PREFIX|g" \
      -e "s|<COGNITO_POOL_ID>|$COGNITO_POOL_ID|g" \
      -e "s|<COGNITO_CLIENT_ID>|$COGNITO_CLIENT_ID|g" \
      -e "s|<COGNITO_DOMAIN>|$COGNITO_DOMAIN|g" \
      -e "s|<LOCAL_CALLBACK_URL>|$LOCAL_CALLBACK_URL|g" \
      -e "s|<EKS_CLUSTER>|$EKS_CLUSTER|g" \
      -e "s|<HYPERPOD_CLUSTER>|$HYPERPOD_CLUSTER|g" \
      -e "s|<LOG_GROUP_NAME>|$LOG_GROUP_NAME|g" \
      -e "s|<FSX_FILESYSTEMS>|$FSX_FILESYSTEMS|g" \
      -e "s|<AMP_WS_ID>|$AMP_WS_ID|g" \
      -e "s|<IDC_STORE_ID>|$IDC_STORE_ID|g" \
      -e "s|<IDC_REGION>|$IDC_REGION|g" \
      -e "s|<IDC_ASSUME_ROLE_ARN>|$IDC_ASSUME_ROLE_ARN|g" \
      -e "s|<S3_BUCKETS>|$S3_BUCKETS|g" \
      -e "s|<POD_ROLE_ARN>|$POD_ROLE_ARN|g" \
      -e "s|<SSM_ROLE_ARN>|$SSM_ROLE_ARN|g" \
      -e "s|<CODEBUILD_PROJECT>|$CODEBUILD_PROJECT|g" \
      -e "s|<IMAGE_BUILD_BUCKET>|$IMAGE_BUILD_BUCKET|g" \
      -e "s|<CROSS_CLUSTER_MODE>|$CROSS_CLUSTER_MODE|g" \
      -e "s|<KUBE_CONTEXT>|$KUBE_CONTEXT|g" \
      -e "s|<KUBECONFIG_PATH>|$KUBECONFIG_PATH|g" \
      "$1"
}

# kubectl 带 context (跨集群时显式指平台集群)
kc() {
  if [ -n "$APPLY_CONTEXT" ]; then
    kubectl --context "$APPLY_CONTEXT" "$@"
  else
    kubectl "$@"
  fi
}

if [ "$DRY_RUN" = "1" ]; then
  echo ">> --dry-run: 只渲染打印 (不 apply)"
  for f in platform-api platform-controller frontend; do
    echo "===== $f.yaml ====="; render "$K8S_DIR/$f.yaml"
  done
  exit 0
fi

echo ">> 1. 建 namespace (平台集群)"
kc apply -f "$K8S_DIR/namespace.yaml"

# 跨集群: 自动生成业务集群 kubeconfig + 建/更新 cross-cluster-kubeconfig secret.
# 后端 pod 挂载它远程连业务集群 (exec 模式, aws eks get-token 自动轮转).
# 可用 SKIP_KUBECONFIG_SECRET=1 跳过 (已手动建好时).
if [ "$CROSS_CLUSTER_MODE" = "true" ] && [ "${SKIP_KUBECONFIG_SECRET:-0}" != "1" ]; then
  echo ">> 1.5 建业务集群 kubeconfig secret (跨集群)"
  # ⚠️ 不用 `aws eks update-kubeconfig` 生成: 本地有 AWS_PROFILE 时它会把
  # env: AWS_PROFILE=xxx 烤进 exec 段, 带到 pod 里 (pod 无此 profile, 走 Pod
  # Identity) 会让 aws eks get-token 报 "profile could not be found"。
  # 这里手写一份最小 kubeconfig, exec 段不含任何 env, pod 走默认凭证链。
  BK="$(mktemp)"
  EP="$(aws eks describe-cluster --name "$BUSINESS_CLUSTER" --region "$REGION" \
    --query 'cluster.endpoint' --output text)"
  CA="$(aws eks describe-cluster --name "$BUSINESS_CLUSTER" --region "$REGION" \
    --query 'cluster.certificateAuthority.data' --output text)"
  cat > "$BK" <<EOF
apiVersion: v1
kind: Config
clusters:
- name: $KUBE_CONTEXT
  cluster:
    server: $EP
    certificate-authority-data: $CA
contexts:
- name: $KUBE_CONTEXT
  context:
    cluster: $KUBE_CONTEXT
    user: $KUBE_CONTEXT
current-context: $KUBE_CONTEXT
users:
- name: $KUBE_CONTEXT
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1beta1
      command: aws
      args:
      - --region
      - $REGION
      - eks
      - get-token
      - --cluster-name
      - $BUSINESS_CLUSTER
      - --output
      - json
EOF
  # create-or-update (--dry-run|apply 幂等, secret 已存在也不报错)
  kc -n "$PLATFORM_NS" create secret generic cross-cluster-kubeconfig \
    --from-file=config="$BK" \
    --dry-run=client -o yaml | kc apply -f -
  rm -f "$BK"
  echo "   ✓ secret cross-cluster-kubeconfig 已就绪 (context=$KUBE_CONTEXT)"
fi

echo ">> 2. 渲染 + apply 后端/前端 (平台集群)"
for f in platform-api platform-controller frontend; do
  render "$K8S_DIR/$f.yaml" | kc apply -f -
done

echo ">> 3. 渲染 + apply ingress (平台集群 internal ALB)"
# albCertificateArn 非空: 开 HTTPS:443 + HTTP:80 自动 301 跳转
# 留空: 仅 HTTP:80 (开发环境/无证书)
if [ -n "$ALB_CERT_ARN" ]; then
  ALB_HTTPS_ANNOTATIONS=$(cat <<EOF
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTP":80},{"HTTPS":443}]'
    alb.ingress.kubernetes.io/certificate-arn: $ALB_CERT_ARN
    alb.ingress.kubernetes.io/ssl-policy: ELBSecurityPolicy-TLS13-1-2-2021-06
    alb.ingress.kubernetes.io/ssl-redirect: '443'
EOF
)
  echo "   ✓ HTTPS 已启用 (cert=$ALB_CERT_ARN)"
else
  ALB_HTTPS_ANNOTATIONS='    alb.ingress.kubernetes.io/listen-ports: '"'"'[{"HTTP":80}]'"'"
  echo "   ⚠️ albCertificateArn 为空, 仅开 HTTP:80"
fi
# 多行注入: sed 单行 s 命令搞不定, 用 awk 把整行 <ALB_HTTPS_ANNOTATIONS> 替换为多行块.
# 精确匹配整行 (不能用 substring 匹配, 否则注释里提到该字符串也会被替换).
awk -v repl="$ALB_HTTPS_ANNOTATIONS" '
  $0 == "<ALB_HTTPS_ANNOTATIONS>" { print repl; next }
  { print }
' "$K8S_DIR/ingress.yaml" | kc apply -f -

echo ">> 完成. 查状态:"
echo "   kubectl --context ${APPLY_CONTEXT:-<current>} -n $PLATFORM_NS get pods,ingress"