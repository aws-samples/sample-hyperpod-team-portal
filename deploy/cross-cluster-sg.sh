#!/usr/bin/env bash
#
# 跨集群安全组放行: 让平台后端 pod 能连业务集群开发机 pod 的 8888(jupyter/code)+ 443(AMP)。
# 不放则: 后端连不上开发机 → 浏览器开开发机 504; 平台查 AMP 失败。
#
# 自动查两个 SG (不用手填, 不用先建开发机):
#   DST_SG = HyperPod 集群 VpcConfig 的 SG (= 开发机 pod ENI 所在 SG, 业务集群 ENABLE_POD_ENI=false)
#   SRC_SG = 平台集群节点实例的 SG (后端 pod 走节点 ENI 出网, 故源是节点 SG, 非 ALB/pod-traffic SG)
#
# 用法:
#   ./deploy/cross-cluster-sg.sh          # 自动查 + 放行 8888/443
#   ./deploy/cross-cluster-sg.sh verify   # 只查 SG 打印, 不改
#
# 前提: cluster-init.sh 已写好 kubeconfig (平台集群 context); aws/kubectl 可用; cdk.json 已填。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CDK_JSON="$ROOT/infrastructure/cdk.json"
ctx() { python3 -c "import json,sys; print(json.load(open('$CDK_JSON'))['context'].get('$1',''))"; }

REGION="$(ctx region)"
PROJECT="$(ctx projectName)"
HYPERPOD_CLUSTER="$(ctx hyperpodClusterName)"
PLATFORM_CLUSTER="${PROJECT}-$(ctx platformClusterSuffix)"
PLATFORM_CTX="${PLATFORM_CONTEXT:-$PLATFORM_CLUSTER}"

VERIFY_ONLY=0
[ "${1:-}" = "verify" ] && VERIFY_ONLY=1

echo ">> region=$REGION  hyperpod=$HYPERPOD_CLUSTER  平台集群=$PLATFORM_CLUSTER"

# ---- DST_SG: HyperPod 集群配置里的 SG (= 开发机 pod ENI SG) ----
DST_SG="$(aws sagemaker describe-cluster --cluster-name "$HYPERPOD_CLUSTER" --region "$REGION" \
  --query "VpcConfig.SecurityGroupIds[0]" --output text 2>/dev/null)"
if [ -z "$DST_SG" ] || [ "$DST_SG" = "None" ]; then
  echo "❌ 取不到 HyperPod 集群 SG (cluster=$HYPERPOD_CLUSTER 对吗?)" >&2; exit 1
fi

# ---- SRC_SG: 平台集群节点实例的 SG (后端 pod 走节点 ENI 出网) ----
NODE="$(kubectl --context "$PLATFORM_CTX" -n platform-system \
  get pod -l app=platform-api -o jsonpath='{.items[0].spec.nodeName}' 2>/dev/null)"
if [ -z "$NODE" ]; then
  echo "❌ 取不到平台后端 pod 所在节点 (后端是否已部署? context=$PLATFORM_CTX)" >&2; exit 1
fi
INSTANCE="$(aws ec2 describe-instances --region "$REGION" \
  --filters "Name=private-dns-name,Values=$NODE" \
  --query "Reservations[0].Instances[0].InstanceId" --output text 2>/dev/null)"
SRC_SG="$(aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE" \
  --query "Reservations[0].Instances[0].NetworkInterfaces[0].Groups[0].GroupId" --output text 2>/dev/null)"
if [ -z "$SRC_SG" ] || [ "$SRC_SG" = "None" ]; then
  echo "❌ 取不到平台节点 SG (node=$NODE instance=$INSTANCE)" >&2; exit 1
fi

echo "   DST_SG=$DST_SG (开发机 pod / HyperPod 节点)  SRC_SG=$SRC_SG (平台节点)"
if [ "$VERIFY_ONLY" = "1" ]; then echo ">> verify 模式, 不改"; exit 0; fi

# ---- 放行 8888 + 443 (幂等: 已存在则忽略) ----
for PORT in 8888 443; do
  if aws ec2 authorize-security-group-ingress --region "$REGION" \
       --group-id "$DST_SG" --protocol tcp --port "$PORT" --source-group "$SRC_SG" >/dev/null 2>&1; then
    echo "   ✓ 放行 $PORT (源 $SRC_SG → $DST_SG)"
  else
    echo "   ($PORT 规则已存在, 跳过)"
  fi
done

# ---- 开发机 directSSH: 放行 22222 (幂等) ----
# 仅当 cdk.json 填了 directSshDomain (启用 directSSH) 才放。来源 = 业务 VPC CIDR:
# ssh 是用户从客户端 (VPC 内 / 已打通网络) 直连开发机, 不像 8888/443 走平台节点,
# 故按 VPC 内网段放通 (符合内网访问, 无公网入口)。DST_SG 同上 = 开发机 pod ENI SG。
DIRECT_SSH_DOMAIN="$(ctx directSshDomain)"
if [ -n "$DIRECT_SSH_DOMAIN" ]; then
  VPC_ID="$(ctx vpcId)"
  # 取 VPC 全部 CIDR block (含 secondary): 开发机 pod / 客户端可能落在任一段。
  # ⚠️ 只取 primary CidrBlock 会漏 —— 实测 pod 常在 secondary 段 (如 10.1.0.0/16),
  # 只放 primary 则 ssh 连不上。故遍历 CidrBlockAssociationSet 每段都放。
  VPC_CIDRS="$(aws ec2 describe-vpcs --region "$REGION" --vpc-ids "$VPC_ID" \
    --query 'Vpcs[0].CidrBlockAssociationSet[].CidrBlock' --output text 2>/dev/null)"
  if [ -z "$VPC_CIDRS" ] || [ "$VPC_CIDRS" = "None" ]; then
    echo "   ⚠️ 取不到 VPC CIDR (vpcId=$VPC_ID), 跳过 22222 放行 (可手动补)" >&2
  else
    for CIDR in $VPC_CIDRS; do
      if aws ec2 authorize-security-group-ingress --region "$REGION" \
           --group-id "$DST_SG" --protocol tcp --port 22222 --cidr "$CIDR" >/dev/null 2>&1; then
        echo "   ✓ 放行 22222 (源 $CIDR → $DST_SG, directSSH)"
      else
        echo "   (22222 源 $CIDR 规则已存在, 跳过)"
      fi
    done
  fi
fi

echo ">> 完成。验证 (后端 pod 连开发机, 毫秒级=通): 起开发机后"
echo "   kubectl --context $PLATFORM_CTX -n platform-system exec deploy/platform-api -- \\"
echo "     curl -s -m 10 -o /dev/null -w '%{http_code} %{time_total}s\\n' http://<开发机podIP>:8888/"
