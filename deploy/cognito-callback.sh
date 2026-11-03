#!/usr/bin/env bash
#
# 设置 Cognito App Client 的 callback URL + 关联登录 IdP。
#
# ⚠️ 职责已变 (2026-07): callback 现已由 CDK 直接拼好 —— cdk.json 填了 albDomainName 时,
#    CDK 建 client 就写好 https://<域名>/auth/callback, 无需本脚本回填。
#    本脚本现在的主要用途是【关联 SAML IdP】: CDK 无法引用部署后才手建的 SAML provider
#    (要先有 provider 才能关联, 鸡生蛋), 故接 IdC SAML 登录时用本脚本把 client 的
#    supported-identity-providers 指到该 provider (CDK 默认只放 COGNITO)。
#
# 何时仍需跑:
#   - 接 IdC SAML: 建好 SAML provider 后, IDP_NAME=<provider名> 跑本脚本关联 (必须)
#   - albDomainName 留空 (联调走 localhost/SSM 隧道): CDK 写的是 localhost 占位, 用本脚本回填真实 callback
#   - cdk deploy 若冲掉了 client 配置: 一键恢复 callback + IdP
#
# pool/client 从 CDK Output 取; callback 默认从 cdk.json albDomainName 拼
# https://<域名>/auth/callback (与 CDK / 后端一致, 避免 redirect_mismatch)。
#
# 用法:
#   IDP_NAME=my-idc-saml ./deploy/cognito-callback.sh              # 接 IdC SAML: 关联该 IdP (常用)
#   ./deploy/cognito-callback.sh                                   # 仅回填 callback (IdP=COGNITO)
#   CALLBACK_URL=https://other.example.com/auth/callback ./deploy/cognito-callback.sh   # 覆盖 callback
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CDK_JSON="$ROOT/infrastructure/cdk.json"

ctx() { python3 -c "import json,sys; print(json.load(open('$CDK_JSON'))['context'].get('$1',''))"; }
PROJECT="$(ctx projectName)"
REGION="$(ctx region)"
STACK="${STACK:-${PROJECT}-platform-stack}"

out() {
  aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text 2>/dev/null
}

# pool/client: 命令行 env > CDK Output。IdP 默认 COGNITO (原生用户池)。
POOL_ID="${COGNITO_POOL_ID:-$(out CognitoUserPoolId)}"
CLIENT_ID="${COGNITO_CLIENT_ID:-$(out CognitoClientId)}"
IDP_NAME="${IDP_NAME:-COGNITO}"
# callback 默认从 cdk.json albDomainName 拼 (与 render-and-apply.sh 后端一致); CALLBACK_URL 可覆盖。
CALLBACK_URL="${CALLBACK_URL:-https://$(ctx albDomainName)/auth/callback}"

if [ -z "$POOL_ID" ] || [ -z "$CLIENT_ID" ]; then
  echo "❌ 取不到 Cognito pool/client (Stack $STACK Output 为空)" >&2
  echo "   显式指定: COGNITO_POOL_ID=.. COGNITO_CLIENT_ID=.. $0" >&2
  exit 1
fi

# callback 列表: 主 callback + 可选追加 (空格分隔)
CALLBACKS="$CALLBACK_URL"
[ -n "${EXTRA_CALLBACKS:-}" ] && CALLBACKS="$CALLBACKS $EXTRA_CALLBACKS"

echo ">> pool=$POOL_ID client=$CLIENT_ID idp=$IDP_NAME"
echo "   callbacks=$CALLBACKS"

# shellcheck disable=SC2086
aws cognito-idp update-user-pool-client --region "$REGION" \
  --user-pool-id "$POOL_ID" --client-id "$CLIENT_ID" \
  --callback-urls $CALLBACKS \
  --allowed-o-auth-flows code --allowed-o-auth-scopes openid email profile \
  --supported-identity-providers "$IDP_NAME" --allowed-o-auth-flows-user-pool-client \
  >/dev/null

echo ">> ✓ Cognito callback 已回填: $CALLBACKS"
