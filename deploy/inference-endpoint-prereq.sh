#!/usr/bin/env bash
# =============================================================================
# 推理 Endpoint 网络/IAM 基建一键脚本 (跨 region 可重复执行, 幂等)
#
# 目的: 让 HyperPod Inference endpoint 的 endpoint_url 端到端打通 —— ingress 拿到
#   ALB DNS → target healthy → SageMaker endpoint InService → endpoint_url 可用。
#   处理六类已知部署问题 + 2026-06-15 实测新坑 (subnet IP 耗尽 / SageMaker 僵尸 ENI)。
#
# 覆盖 (与 deploy.sh stage_inference_operator 3.6.1b~1e 等价, 抽成独立可重跑):
#   1. ALB Controller IRSA Role (建/更新 trust + attach 官方 policy v2.13.0)
#   2. EKS subnet 打 kubernetes.io/role/internal-elb=1 tag
#   3. 节点 SG 放行 tcp 8081(IEC sidecar) + 30000(llm-d gateway) ← ALB 侧
#      (优先引用 ALB backend SG, 回落到 internal-elb tag 子网的 CIDR)
#   4. S3 Gateway endpoint 关联推理 subnet 的路由表 (router 下 TLS 证书)
#   5. add-on 传真 ALB roleArn + 重启 ALB controller
#   6. [新坑] internal-elb subnet IP 容量体检 (internal ALB 每子网需 ≥8 空闲 IP)
#   7. [新坑] SageMaker 僵尸 ENI 清扫 (endpoint 删后 available ENI 占满子网 IP)
#
# 用法:
#   chmod +x inference-endpoint-prereq.sh
#   AWS_PROFILE=hypd-029 AWS_REGION=us-east-1 \
#     EKS_CLUSTER_NAME=eks-xxx HP_CLUSTER_NAME=hp-cluster-xxx \
#     ./inference-endpoint-prereq.sh
#
#   # 仅体检 + 清扫僵尸 ENI (不碰 IAM/SG/tag):
#   ONLY_ENI_SWEEP=1 EKS_CLUSTER_NAME=eks-xxx ./inference-endpoint-prereq.sh
#
#   # 僵尸 ENI 只看不删 (dry-run):
#   ENI_DRY_RUN=1 EKS_CLUSTER_NAME=eks-xxx ./inference-endpoint-prereq.sh
#
# 必填 env: EKS_CLUSTER_NAME, HP_CLUSTER_NAME (ONLY_ENI_SWEEP 时 HP 可省)
# 选填 env: AWS_REGION(默 us-west-2) AWS_PROFILE INFERENCE_ALB_ROLE_NAME
#           ALB_POLICY_VERSION(默 v2.13.0) ENI_DRY_RUN ONLY_ENI_SWEEP MIN_FREE_IP(默 8)
# =============================================================================
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-west-2}"
EKS_CLUSTER_NAME="${EKS_CLUSTER_NAME:?必须设 EKS_CLUSTER_NAME}"
HP_CLUSTER_NAME="${HP_CLUSTER_NAME:-}"
ALB_POLICY_VERSION="${ALB_POLICY_VERSION:-v2.13.0}"   # 需含 DescribeListenerAttributes
MIN_FREE_IP="${MIN_FREE_IP:-8}"                       # internal ALB 每子网最低空闲 IP 门槛
ENI_DRY_RUN="${ENI_DRY_RUN:-0}"
ONLY_ENI_SWEEP="${ONLY_ENI_SWEEP:-0}"

# region 派生默认名 (允许覆盖)
INFERENCE_ALB_ROLE_NAME="${INFERENCE_ALB_ROLE_NAME:-${EKS_CLUSTER_NAME}-inference-alb-role}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERR]${NC} $*"; }

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
log "Account=${ACCOUNT_ID} Region=${AWS_REGION} EKS=${EKS_CLUSTER_NAME}"

# 公共: VPC / subnets (多处用)
EKS_VPC=$(aws eks describe-cluster --name "${EKS_CLUSTER_NAME}" --region "${AWS_REGION}" \
  --query 'cluster.resourcesVpcConfig.vpcId' --output text)
EKS_SUBNETS=$(aws eks describe-cluster --name "${EKS_CLUSTER_NAME}" --region "${AWS_REGION}" \
  --query 'cluster.resourcesVpcConfig.subnetIds' --output text)
log "VPC=${EKS_VPC}"

# =============================================================================
# 7. SageMaker 僵尸 ENI 清扫
#    根因: 推理 endpoint/实例删除后, SageMaker managed ENI 残留 status=available
#    不被 AWS 回收, 累积占满子网 IP → 后续 ALB insufficient available IP addresses。
#    安全: 只删 Status=available 的 SageMaker ENI (available = 没挂任何活实例)。
# =============================================================================
sweep_orphan_eni() {
  log "===== [新坑7] SageMaker 僵尸 ENI 清扫 (VPC ${EKS_VPC}) ====="
  local enis
  enis=$(aws ec2 describe-network-interfaces --region "${AWS_REGION}" \
    --filters "Name=vpc-id,Values=${EKS_VPC}" "Name=status,Values=available" \
    --query "NetworkInterfaces[?contains(Description, 'SageMaker managed ENI')].NetworkInterfaceId" \
    --output text 2>/dev/null || echo "")
  if [[ -z "${enis}" ]]; then
    ok "无 available 的 SageMaker 僵尸 ENI"
    return 0
  fi
  local n=0
  for eni in ${enis}; do
    # 二次确认 status (并发安全)
    local st desc
    st=$(aws ec2 describe-network-interfaces --network-interface-ids "${eni}" --region "${AWS_REGION}" \
      --query 'NetworkInterfaces[0].Status' --output text 2>/dev/null || echo "missing")
    [[ "${st}" != "available" ]] && { warn "${eni} status=${st}, 跳过"; continue; }
    desc=$(aws ec2 describe-network-interfaces --network-interface-ids "${eni}" --region "${AWS_REGION}" \
      --query 'NetworkInterfaces[0].Description' --output text 2>/dev/null)
    if [[ "${ENI_DRY_RUN}" == "1" ]]; then
      warn "[dry-run] 将删 ${eni} (${desc})"
    else
      aws ec2 delete-network-interface --network-interface-id "${eni}" --region "${AWS_REGION}" \
        && { ok "删僵尸 ENI ${eni} (${desc})"; n=$((n+1)); } \
        || err "删 ${eni} 失败"
    fi
  done
  ok "僵尸 ENI 清扫完成 (删 ${n} 个; dry-run=${ENI_DRY_RUN})"
}

# =============================================================================
# 6. internal-elb subnet IP 容量体检
#    internal ALB 每子网需 ≥MIN_FREE_IP 空闲 IP (伸缩 headroom), 否则建不出。
#    /28 子网 (16 IP, 11 可用) 几乎必然不够, 应用 /24+ 大子网。
# =============================================================================
check_subnet_capacity() {
  log "===== [新坑6] internal-elb subnet IP 容量体检 (门槛 ${MIN_FREE_IP}) ====="
  local tagged
  tagged=$(aws ec2 describe-subnets --region "${AWS_REGION}" \
    --filters "Name=vpc-id,Values=${EKS_VPC}" \
      "Name=tag:kubernetes.io/role/internal-elb,Values=1" \
    --query 'Subnets[].[SubnetId,AvailabilityZone,CidrBlock,AvailableIpAddressCount]' \
    --output text 2>/dev/null || echo "")
  if [[ -z "${tagged}" ]]; then
    warn "无 internal-elb tag 的 subnet —— 先跑 tag 步骤 (步骤2)"
    return 0
  fi
  local bad=0 azset=""
  while IFS=$'\t' read -r sid az cidr free; do
    [[ -z "${sid}" ]] && continue
    azset="${azset} ${az}"
    if (( free < MIN_FREE_IP )); then
      err "  ${sid} (${az} ${cidr}) 空闲 IP=${free} < ${MIN_FREE_IP} ✗ ALB 可能建不出"
      bad=$((bad+1))
    else
      ok "  ${sid} (${az} ${cidr}) 空闲 IP=${free} ✓"
    fi
  done <<< "${tagged}"
  local az_count
  az_count=$(echo "${azset}" | tr ' ' '\n' | grep -v '^$' | sort -u | wc -l | tr -d ' ')
  (( az_count < 2 )) && err "internal-elb subnet 只覆盖 ${az_count} 个 AZ (internal ALB 需 ≥2 AZ) ✗"
  if (( bad > 0 )); then
    warn "有 ${bad} 个 subnet IP 不足。建议: 把 internal-elb tag 移到 /24+ 大私有子网 (≥2 AZ),"
    warn "  或先跑僵尸 ENI 清扫 (本脚本步骤7) 释放 IP。/28 子网不适合放 internal ALB。"
  fi
}

# ONLY_ENI_SWEEP: 只体检 + 清扫, 不碰 IAM/SG/tag
if [[ "${ONLY_ENI_SWEEP}" == "1" ]]; then
  sweep_orphan_eni
  check_subnet_capacity
  ok "仅 ENI 清扫 + 容量体检完成"
  exit 0
fi

# =============================================================================
# 1. ALB Controller IRSA Role
# =============================================================================
log "===== ALB Controller IRSA Role ====="
OIDC_ISSUER=$(aws eks describe-cluster --name "${EKS_CLUSTER_NAME}" --region "${AWS_REGION}" \
  --query 'cluster.identity.oidc.issuer' --output text)
OIDC_NO_HTTPS="${OIDC_ISSUER#https://}"
OIDC_PROVIDER_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/${OIDC_NO_HTTPS}"

# OIDC provider 不存在则建
if ! aws iam get-open-id-connect-provider --open-id-connect-provider-arn "${OIDC_PROVIDER_ARN}" >/dev/null 2>&1; then
  log "建 IAM OIDC provider..."
  aws iam create-open-id-connect-provider --url "${OIDC_ISSUER}" \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 9e99a48a9960b14926bb7f3b02e22da2b0ab7280 >/dev/null
fi

ALB_TRUST=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "${OIDC_PROVIDER_ARN}"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "${OIDC_NO_HTTPS}:aud": "sts.amazonaws.com",
        "${OIDC_NO_HTTPS}:sub": "system:serviceaccount:hyperpod-inference-system:aws-load-balancer-controller"
      }
    }
  }]
}
EOF
)
ALB_ROLE_ARN=$(aws iam get-role --role-name "${INFERENCE_ALB_ROLE_NAME}" --query 'Role.Arn' --output text 2>/dev/null || echo "")
if [[ -z "${ALB_ROLE_ARN}" || "${ALB_ROLE_ARN}" == "None" ]]; then
  log "建 ALB Role ${INFERENCE_ALB_ROLE_NAME}..."
  ALB_ROLE_ARN=$(aws iam create-role --role-name "${INFERENCE_ALB_ROLE_NAME}" \
    --assume-role-policy-document "${ALB_TRUST}" --query 'Role.Arn' --output text)
else
  log "更新 ALB Role trust..."
  aws iam update-assume-role-policy --role-name "${INFERENCE_ALB_ROLE_NAME}" --policy-document "${ALB_TRUST}"
fi

# 官方 ALB controller IAM policy (v2.13.0 起含 DescribeListenerAttributes)
ALB_POLICY_NAME="${INFERENCE_ALB_ROLE_NAME}-policy"
ALB_POLICY_ARN=$(aws iam list-policies --scope Local \
  --query "Policies[?PolicyName=='${ALB_POLICY_NAME}'].Arn" --output text 2>/dev/null || echo "")
if [[ -z "${ALB_POLICY_ARN}" || "${ALB_POLICY_ARN}" == "None" ]]; then
  log "拉官方 ALB IAM policy ${ALB_POLICY_VERSION} + 建 ${ALB_POLICY_NAME}..."
  ALB_POLICY_JSON="/tmp/alb-iam-policy-${EKS_CLUSTER_NAME}.json"
  curl -fsSL -o "${ALB_POLICY_JSON}" \
    "https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/${ALB_POLICY_VERSION}/docs/install/iam_policy.json" \
    || { err "拉 ALB IAM policy 失败 (检查网络)"; exit 1; }
  ALB_POLICY_ARN=$(aws iam create-policy --policy-name "${ALB_POLICY_NAME}" \
    --policy-document "file://${ALB_POLICY_JSON}" --query 'Policy.Arn' --output text)
else
  log "ALB policy ${ALB_POLICY_NAME} 已存在 (如需升级版本: 手动 create-policy-version --set-as-default)"
fi
aws iam attach-role-policy --role-name "${INFERENCE_ALB_ROLE_NAME}" --policy-arn "${ALB_POLICY_ARN}" 2>/dev/null || true
ok "ALB Role ARN: ${ALB_ROLE_ARN}"

# =============================================================================
# 2. EKS subnet 打 internal-elb tag
# =============================================================================
log "===== subnet internal-elb tag ====="
for sn in ${EKS_SUBNETS}; do
  aws ec2 create-tags --region "${AWS_REGION}" --resources "${sn}" \
    --tags Key=kubernetes.io/role/internal-elb,Value=1 2>/dev/null \
    && ok "  ${sn} 打 tag" || warn "  ${sn} tag 失败/已存在"
done

# =============================================================================
# 3. 节点 SG 放行 ALB 健康检查端口
#    8081  = IEC reverse-proxy sidecar
#    30000 = llm-d gateway (sgl-model-gateway)
# =============================================================================

# 给节点 SG 放行 tcp <port> ← ALB 侧。ALB 建成后 backend SG 才存在, 故分两条路。
allow_alb_to_node() {
  local node_sg="$1" port="$2" vpc="$3" alb_sg cidrs c

  # 首选: 引用 ALB backend SG。最精确, 且与 IP 网段规划无关。
  alb_sg=$(aws ec2 describe-security-groups --region "${AWS_REGION}" \
    --filters "Name=vpc-id,Values=${vpc}" "Name=group-name,Values=k8s-traffic-*" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "")
  if [[ -n "${alb_sg}" && "${alb_sg}" != "None" ]]; then
    aws ec2 authorize-security-group-ingress --region "${AWS_REGION}" \
      --group-id "${node_sg}" --protocol tcp --port "${port}" --source-group "${alb_sg}" 2>/dev/null \
      && ok "  ${node_sg} 放行 ${alb_sg} → ${port}" || warn "  ${port} ← ${alb_sg} 已存在 (跳过)"
    return 0
  fi

  # 回落 (首次部署, ALB 从未建过): 放行【打了 internal-elb tag 的子网】的 CIDR。
  # 不用 Vpcs[0].CidrBlock —— 它只返主 CIDR, 多 CIDR VPC 下会漏掉 ALB 实际所在的
  # secondary 网段, 放行了照样 Target.Timeout (§6 第6项实测)。ALB 只会落在
  # 带此 tag 的子网 (controller 的子网发现规则), 故这是最小且完整的范围。
  cidrs=$(aws ec2 describe-subnets --region "${AWS_REGION}" \
    --filters "Name=vpc-id,Values=${vpc}" \
              "Name=tag:kubernetes.io/role/internal-elb,Values=1" \
    --query 'Subnets[].CidrBlock' --output text)
  if [[ -z "${cidrs}" ]]; then
    warn "  无 internal-elb tag 子网, 跳过 ${port} (先跑步骤2 打 tag)"
    return 0
  fi
  for c in ${cidrs}; do
    aws ec2 authorize-security-group-ingress --region "${AWS_REGION}" \
      --group-id "${node_sg}" --protocol tcp --port "${port}" --cidr "${c}" 2>/dev/null \
      && ok "  ${node_sg} 放行 ${c} → ${port}" || warn "  ${port} ← ${c} 已存在 (跳过)"
  done
}

log "===== 节点 SG 放行 tcp 8081(IEC) + 30000(llm-d) ← ALB 侧 ====="
if [[ -z "${HP_CLUSTER_NAME}" ]]; then
  warn "未设 HP_CLUSTER_NAME, 跳过 SG 放行 (ALB 健康检查会 timeout)"
else
  HP_NODE_SG=$(aws sagemaker describe-cluster --cluster-name "${HP_CLUSTER_NAME}" --region "${AWS_REGION}" \
    --query 'VpcConfig.SecurityGroupIds[0]' --output text 2>/dev/null || echo "")
  if [[ -n "${HP_NODE_SG}" && "${HP_NODE_SG}" != "None" ]]; then
    SG_VPC=$(aws ec2 describe-security-groups --group-ids "${HP_NODE_SG}" --region "${AWS_REGION}" \
      --query 'SecurityGroups[0].VpcId' --output text)
    allow_alb_to_node "${HP_NODE_SG}" 8081  "${SG_VPC}"
    allow_alb_to_node "${HP_NODE_SG}" 30000 "${SG_VPC}"
  else
    warn "拿不到 HP cluster SG, 跳过 SG 放行"
  fi
fi

# =============================================================================
# 4. S3 Gateway endpoint 关联推理 subnet 路由表
# =============================================================================
log "===== S3 Gateway endpoint 关联路由表 ====="
S3_VPCE=$(aws ec2 describe-vpc-endpoints --region "${AWS_REGION}" \
  --filters "Name=vpc-id,Values=${EKS_VPC}" "Name=service-name,Values=com.amazonaws.${AWS_REGION}.s3" \
  --query 'VpcEndpoints[0].VpcEndpointId' --output text 2>/dev/null || echo "")
if [[ -n "${S3_VPCE}" && "${S3_VPCE}" != "None" ]]; then
  FIRST_SUBNET="${EKS_SUBNETS%% *}"
  INFER_RT=$(aws ec2 describe-route-tables --region "${AWS_REGION}" \
    --filters "Name=vpc-id,Values=${EKS_VPC}" "Name=association.subnet-id,Values=${FIRST_SUBNET}" \
    --query 'RouteTables[0].RouteTableId' --output text 2>/dev/null || echo "")
  if [[ -z "${INFER_RT}" || "${INFER_RT}" == "None" ]]; then
    INFER_RT=$(aws ec2 describe-route-tables --region "${AWS_REGION}" \
      --filters "Name=vpc-id,Values=${EKS_VPC}" "Name=association.main,Values=true" \
      --query 'RouteTables[0].RouteTableId' --output text 2>/dev/null || echo "")
  fi
  if [[ -n "${INFER_RT}" && "${INFER_RT}" != "None" ]]; then
    aws ec2 modify-vpc-endpoint --region "${AWS_REGION}" \
      --vpc-endpoint-id "${S3_VPCE}" --add-route-table-ids "${INFER_RT}" 2>/dev/null \
      && ok "  S3 endpoint ${S3_VPCE} 关联路由表 ${INFER_RT}" || warn "  已关联 (跳过)"
  fi
else
  warn "无 S3 Gateway endpoint —— router 可能连不上 S3 (需先建 S3 Gateway endpoint)"
fi

# =============================================================================
# 5. add-on 传真 ALB roleArn + 重启 ALB controller (承接第 1 步)
#    add-on 改 SA 注解但不自动重启 controller pod, 必须手动 rollout restart。
# =============================================================================
log "===== add-on 配置真 ALB role + 重启 controller ====="
ADDON_NAME="amazon-sagemaker-hyperpod-inference"
if aws eks describe-addon --cluster-name "${EKS_CLUSTER_NAME}" --addon-name "${ADDON_NAME}" \
     --region "${AWS_REGION}" >/dev/null 2>&1; then
  CFG=$(printf '{"alb":{"serviceAccount":{"create":true,"roleArn":"%s"}}}' "${ALB_ROLE_ARN}")
  aws eks update-addon --cluster-name "${EKS_CLUSTER_NAME}" --addon-name "${ADDON_NAME}" \
    --region "${AWS_REGION}" --configuration-values "${CFG}" \
    --resolve-conflicts OVERWRITE 2>/dev/null \
    && ok "  add-on 传 ALB roleArn" || warn "  add-on update 跳过 (检查 addon 是否就绪)"
  if command -v kubectl >/dev/null 2>&1; then
    kubectl -n hyperpod-inference-system rollout restart deploy hyperpod-inference-alb 2>/dev/null \
      && ok "  重启 ALB controller (读新 SA role)" \
      || warn "  rollout restart 跳过 (deploy 名可能不同, 手动: kubectl -n hyperpod-inference-system get deploy)"
  else
    warn "  无 kubectl, 手动重启: kubectl -n hyperpod-inference-system rollout restart deploy hyperpod-inference-alb"
  fi
else
  warn "add-on ${ADDON_NAME} 未安装, 跳过配置 (需先装推理 operator add-on)"
fi

# =============================================================================
# 6+7. 新坑: 僵尸 ENI 清扫 + subnet 容量体检 (放最后, 收尾兜底)
# =============================================================================
sweep_orphan_eni
check_subnet_capacity

echo
ok "推理 endpoint 基建脚本执行完成 (region=${AWS_REGION})"
log "验证: kubectl get ingress -A | grep alb-   (应有 ADDRESS)"
log "      新建推理 → endpoint InService → endpoint_url 可用"
