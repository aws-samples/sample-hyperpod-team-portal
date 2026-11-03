#!/usr/bin/env bash
#
# 业务集群 Prerequisites orchestrator — 把 deployment-guideline.md §3+§4 的手动步骤串起来。
# 在 HyperPod 控制台 custom setup 建好 EKS+HyperPod 之后、CDK 之前跑。
#
#   verify    → §3 验证 custom setup 产物 (list-addons, 只读)
#   ebs       → §4.1a EBS CSI: 建 role(+SageMaker inline) + add-on + Pod Identity 关联 + 重启
#   ssm       → §4.1b SSM Managed Node role (spaces 远程访问要它当参数, trust 双 principal)
#   pd        → 开 vpc-cni Prefix Delegation + 装 maxpods-patcher (抬 maxPods 到 110/250).
#               ⭐ 必须在 spaces 之前: 否则 HyperPod 单 ENI 节点 ~29 pod, spaces 装不上 DEGRADED
#   spaces    → §4.1c amazon-sagemaker-spaces add-on。连接方式二选一 (看 cdk.json
#               directSshDomain): 填了→directSSH(原生 SSH+固定 DNS, 关 SSM); 空→remoteAccess(SSM)
#   externaldns → 开发机 directSSH: 自建 Route53 私有 zone + external-dns role/policy
#               + external-dns add-on (监听 SSH Service 同步 DNS 到 zone)。仅
#               directSshDomain 设了才装。zone/role 都脚本自建 (不在 CDK): addon 跑在
#               cdk 前, 依赖 role, role policy 依赖 zone ARN, 三者须先于 CDK。
#   logging   → §4.1d 开容器日志→CloudWatch: 改 add-on configurationValues 的
#               metricsProvider.logging.enabled=true (不是 patch CR, 会被 reconcile 冲)
#               把容器日志推 CloudWatch (训练/开发机日志). 权限走 observability addon 自带 SA, 无需额外 IAM
#   template  → §4.2  两个 WorkspaceTemplate patch allowCustomImages=true (BYOI 必须)
#
# 注: /dev/shm 大小不在这里预置 — 平台建开发机时按 (用户填值 or 资源模板内存 50%) 动态
#     生成一个 per-workspace 的 WorkspaceIntegrationTemplate (与 workspace 同 ns + ownerRef,
#     随 workspace GC), 把内存背书 emptyDir 挂到 /dev/shm (替代运行时默认 64Mi)。
#     集群侧只需 spaces ≥v0.2.0 (WorkspaceIntegrationTemplate CRD, 见 spaces step 版本 pin)。
#   fsxadmin  → §4.4  fsx-admin pod (多 FSx: 读 cdk.json platformFsxFilesystems,
#               一个 pod 挂多块盘到 /fsx-mnt/<fs-id>; DNS/MountName 自动 describe)
#   lws       → llm-d 多机推理: 装 LeaderWorkerSet v0.9.0 (helm oci) +
#               task-governance VAP 窄豁免 (放行 LWS-owned StatefulSet)。平台 Go
#               controller 也 watch LWS CRD, 缺 CRD → controller CrashLoop。
#               ⚠️ VAP 是集群共享, 改动爆炸半径全平台, 生产走变更评审。
#
# 不含 (故意留外面):
#   - §1 VPC/子网/SG, §2 控制台建集群  → 控制台手动
#   - §4.3 建 FSx for Lustre (须 Lustre 2.15) → 控制台手动 (提前建好, 把 fs-id
#     填进 cdk.json platformFsxFilesystems 给 fsxadmin)
#
# ⭐ 所有 IAM role ARN 都用变量预拼 ("arn:aws:iam::${ACCOUNT}:role/xxx"), 避开 zsh
#    把 :role 当 history modifier :r 吃掉导致 ARN 残缺 → "Cross-account pass role" 假象。
#
# 参数 (手动 export, 这步在 CDK 之前, cdk.json 还没填):
#   REGION   必填  如 us-west-2
#   ACCOUNT  必填  12 位账号
#   CLUSTER  必填  EKS 集群名 (custom setup 建的)
#   DATE     可选  role 名后缀, 默认 today (同账号多集群避免 role 名冲突)
#   (fsxadmin 步骤的 FSx 列表读 cdk.json platformFsxFilesystems, 无需 export)
#
# 用法:
#   export REGION=us-west-2 ACCOUNT=123456789012 CLUSTER=my-eks
#   ./deploy/cluster-prereq.sh                       # 全流程 (verify→ebs→ssm→spaces→template)
#   ./deploy/cluster-prereq.sh fsxadmin              # 单跑 fsxadmin (读 cdk.json platformFsxFilesystems)
#   ./deploy/cluster-prereq.sh ebs ssm spaces        # 只补 add-on/role
#   ./deploy/cluster-prereq.sh verify                # 只验证
#
# 前提: 控制台 custom setup 已建好 EKS+HyperPod; aws/kubectl 可用; 凭证就绪 (export AWS_PROFILE=xxx)。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CDK_JSON="$ROOT/infrastructure/cdk.json"

# ---- 入参: 默认从 cdk.json 读 (Step2 填完后跑); env 显式设可覆盖 ----
ctx() { python3 -c "import json,sys; print(json.load(open('$CDK_JSON'))['context'].get('$1',''))" 2>/dev/null; }
REGION="${REGION:-$(ctx region)}"
# account 用当前凭证 (IAM role 建在当前账号; 比 cdk.json 填值更可靠, 避免填错/不一致)
ACCOUNT="${ACCOUNT:-$(aws sts get-caller-identity --query Account --output text 2>/dev/null)}"
CLUSTER="${CLUSTER:-$(ctx businessClusterName)}"   # custom setup 建的业务 EKS 名
# 多 FSx: fsxadmin 步骤读 cdk.json platformFsxFilesystems (逗号分隔 fs-id), 不再单 FS_ID。

: "${REGION:?需要 REGION (cdk.json region 或 export)}"
: "${ACCOUNT:?需要 ACCOUNT (cdk.json account 或 export)}"
: "${CLUSTER:?需要 CLUSTER (cdk.json businessClusterName 或 export CLUSTER)}"
DATE="${DATE:-$(date +%Y%m%d)}"

STEPS=("$@")
# pd 必须在 spaces 之前: 不抬 maxPods, HyperPod 单 ENI 节点只 ~29 pod, 装 spaces 等
# add-on 的 pod 调度不出来 → add-on DEGRADED (InsufficientNumberOfReplicas)。
# externaldns 在 spaces 之后: spaces 开 directSSH 后才会建 SSH Service 供 external-dns
# 同步。未设 directSshDomain 时 externaldns 步骤自跳过 (spaces 也退回 SSM 模式)。
[ ${#STEPS[@]} -eq 0 ] && STEPS=(verify ebs ssm pd spaces externaldns logging template fsxadmin lws)

echo "============================================================"
echo ">> 业务集群 Prerequisites  REGION=$REGION ACCOUNT=$ACCOUNT CLUSTER=$CLUSTER DATE=$DATE"
echo "   steps=${STEPS[*]}"
echo "============================================================"

# ---- 取集群 ARN (EBS trust policy 的 SourceArn 要它) ----
CLUSTER_ARN=""
need_cluster_arn() {
  [ -n "$CLUSTER_ARN" ] && return
  CLUSTER_ARN="$(aws eks describe-cluster --name "$CLUSTER" --region "$REGION" \
    --query cluster.arn --output text)"
  case "$CLUSTER_ARN" in
    arn:aws:eks:*:cluster/*) ;;  # 完整 ARN, cluster/ 没被吃
    *) echo "❌ 取到的 CLUSTER_ARN 不完整: '$CLUSTER_ARN' (cluster 名对吗?)" >&2; exit 1 ;;
  esac
}

ensure_ec2_sg_access() {
  # 在 EC2 部署机上跑时, 放行本机 SG → 业务集群 cluster SG 的 443。
  # 否则集群 private endpoint 下 kubectl/apply 连 API server i/o timeout
  # (NAT 只解决出公网, 连集群 private endpoint 走 VPC 内网 + SG)。
  # 仅 EC2 上 (IMDS 可达) 自动做; mac/本地跳过。
  local token imds_iid ec2_sg cluster_sg
  token="$(curl -s -m 2 -X PUT 'http://169.254.169.254/latest/api/token' \
            -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null || true)"
  imds_iid="$(curl -s -m 2 -H "X-aws-ec2-metadata-token: $token" \
            http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || true)"
  [ -z "$imds_iid" ] && return 0   # 非 EC2, 跳过
  ec2_sg="$(aws ec2 describe-instances --region "$REGION" --instance-ids "$imds_iid" \
    --query 'Reservations[0].Instances[0].NetworkInterfaces[0].Groups[0].GroupId' --output text 2>/dev/null)"
  cluster_sg="$(aws eks describe-cluster --name "$CLUSTER" --region "$REGION" \
    --query 'cluster.resourcesVpcConfig.clusterSecurityGroupId' --output text 2>/dev/null)"
  if [ -n "$ec2_sg" ] && [ "$ec2_sg" != "None" ] && [ -n "$cluster_sg" ] && [ "$cluster_sg" != "None" ]; then
    if aws ec2 authorize-security-group-ingress --region "$REGION" \
         --group-id "$cluster_sg" --protocol tcp --port 443 --source-group "$ec2_sg" >/dev/null 2>&1; then
      echo ">> 已放行 EC2 SG($ec2_sg) → 业务集群 SG($cluster_sg) 443 (EC2 部署机连 private endpoint 必需)"
    else
      echo ">> (SG 443 规则已存在或无需改: $ec2_sg → $cluster_sg)"
    fi
  else
    echo ">> ⚠️ 取 EC2/集群 SG 失败, 跳过 SG 放行 (ec2_sg=$ec2_sg cluster_sg=$cluster_sg)" >&2
  fi
}

step_verify() {
  echo ">>> [verify] §3 验证 custom setup 产物 (只读)"
  aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION" --alias "$CLUSTER" >/dev/null
  echo "   add-on 列表 (重点看 amazon-sagemaker-spaces + aws-ebs-csi-driver 在不在):"
  aws eks list-addons --cluster-name "$CLUSTER" --region "$REGION" --output table
  echo "   Pod Identity 关联 (期望含 ebs-csi-controller-sa / jupyter-k8s-controller-manager):"
  aws eks list-pod-identity-associations --cluster-name "$CLUSTER" --region "$REGION" \
    --query "associations[].serviceAccount" --output text || true
}

step_ebs() {
  echo ">>> [ebs] §4.1a EBS CSI role + add-on + Pod Identity"
  need_cluster_arn
  local EBS_ROLE="AmazonEKS_EBS_CSI_DriverRole-$DATE"
  local ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${EBS_ROLE}"   # ⭐ 预拼, 避开 zsh :role 坑
  echo "   role=$EBS_ROLE  cluster_arn=$CLUSTER_ARN"

  cat > /tmp/ebs-trust.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "pods.eks.amazonaws.com" },
      "Action": [ "sts:AssumeRole", "sts:TagSession" ],
      "Condition": {
        "StringEquals": { "aws:SourceAccount": "$ACCOUNT" },
        "ArnEquals": { "aws:SourceArn": "$CLUSTER_ARN" }
      }
    }
  ]
}
JSON
  python3 -m json.tool < /tmp/ebs-trust.json >/dev/null   # JSON 合法 + 变量填进去了

  # 建 role (幂等: 已存在则更新 trust)
  if aws iam create-role --role-name "$EBS_ROLE" \
       --assume-role-policy-document file:///tmp/ebs-trust.json >/dev/null 2>&1; then
    echo "   ✓ role 已建"
  else
    aws iam update-assume-role-policy --role-name "$EBS_ROLE" \
      --policy-document file:///tmp/ebs-trust.json
    echo "   (role 已存在, trust 已更新)"
  fi
  aws iam attach-role-policy --role-name "$EBS_ROLE" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy
  aws iam put-role-policy --role-name "$EBS_ROLE" \
    --policy-name HyperPodAttachClusterNodeVolume \
    --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["sagemaker:AttachClusterNodeVolume","sagemaker:DetachClusterNodeVolume","sagemaker:DescribeClusterNode","sagemaker:DescribeCluster","sagemaker:ListClusterNodes","eks:DescribeCluster"],"Resource":"*"}]}'

  aws eks create-addon --cluster-name "$CLUSTER" --region "$REGION" \
    --addon-name aws-ebs-csi-driver >/dev/null 2>&1 \
    && echo "   ✓ add-on 已建" || echo "   (add-on 已存在, 跳过)"
  aws eks create-pod-identity-association --cluster-name "$CLUSTER" --region "$REGION" \
    --namespace kube-system --service-account ebs-csi-controller-sa \
    --role-arn "$ROLE_ARN" >/dev/null 2>&1 \
    && echo "   ✓ Pod Identity 关联已建" || echo "   (Pod Identity 关联已存在, 跳过)"
  kubectl -n kube-system rollout restart deploy ebs-csi-controller >/dev/null 2>&1 || true
  echo "   ✓ ebs-csi-controller 已重启"
}

step_ssm() {
  echo ">>> [ssm] §4.1b SSM Managed Node role (trust 双 principal)"
  local SSM_ROLE="sagemaker-space-SSMManagedNode-$DATE"
  local TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":["sagemaker.amazonaws.com","ssm.amazonaws.com"]},"Action":"sts:AssumeRole"}]}'
  if aws iam create-role --role-name "$SSM_ROLE" \
       --assume-role-policy-document "$TRUST" >/dev/null 2>&1; then
    echo "   ✓ role 已建: $SSM_ROLE"
  else
    aws iam update-assume-role-policy --role-name "$SSM_ROLE" --policy-document "$TRUST"
    echo "   (role 已存在, trust 已更新: $SSM_ROLE)"
  fi
  aws iam attach-role-policy --role-name "$SSM_ROLE" \
    --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  echo "   ✓ AmazonSSMManagedInstanceCore 已挂"
}

step_pd() {
  # ⭐ 必须在 spaces 之前: 开 vpc-cni Prefix Delegation + 装 maxpods-patcher 抬 maxPods。
  # HyperPod 节点默认只剩 1 ENI 给 pod (~29), 不抬 maxPods 装 spaces 会 DEGRADED
  # (pod 调度不出来)。PD 是抬 maxPods 的硬前置 (否则 IP 不够, pod 卡 ContainerCreating)。
  echo ">>> [pd] Prefix Delegation + maxpods-patcher (业务集群 $CLUSTER)"
  aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION" --alias "$CLUSTER" >/dev/null

  # 1) vpc-cni 开 PD (EKS managed addon: 改 configurationValues, 持久; 幂等)
  local pd
  pd="$(aws eks describe-addon --cluster-name "$CLUSTER" --region "$REGION" \
        --addon-name vpc-cni --query 'addon.configurationValues' --output text 2>/dev/null \
        | python3 -c "import json,sys; d=sys.stdin.read().strip(); print(json.loads(d).get('env',{}).get('ENABLE_PREFIX_DELEGATION','') if d and d!='None' else '')" 2>/dev/null || true)"
  if [ "$pd" = "true" ]; then
    echo "   ✓ PD 已开启"
  elif aws eks describe-addon --cluster-name "$CLUSTER" --region "$REGION" \
         --addon-name vpc-cni >/dev/null 2>&1; then
    echo "   PD 未开 (当前='$pd'), 开启 ENABLE_PREFIX_DELEGATION=true + WARM_PREFIX_TARGET=1"
    aws eks update-addon --cluster-name "$CLUSTER" --region "$REGION" \
      --addon-name vpc-cni \
      --configuration-values '{"env":{"ENABLE_PREFIX_DELEGATION":"true","WARM_PREFIX_TARGET":"1"}}' \
      --resolve-conflicts OVERWRITE >/dev/null
    echo "   ✓ 已提交 PD (滚动重启 aws-node; 已运行 pod 不受影响)"
  else
    echo "   ⚠️ vpc-cni 非 EKS managed addon, 跳过自动开 PD; 请手动确认 PD 已开" >&2
  fi

  # 2) maxpods-patcher: 每节点按 vCPU 把 kubelet maxPods 抬到 110/250 + 重启 kubelet/ipamd
  kubectl --context "$CLUSTER" apply -f "$SCRIPT_DIR/k8s/maxpods-patcher.yaml"
  kubectl --context "$CLUSTER" -n kube-system rollout status ds/maxpods-patcher --timeout=120s || true
  echo "   ✓ maxpods-patcher 已装 (节点 maxPods 抬高需 ~1min, 之后 spaces 才有 pod 名额)"
}

step_spaces() {
  echo ">>> [spaces] §4.1c amazon-sagemaker-spaces add-on"
  # 连接方式二选一 (由 cdk.json directSshDomain 决定):
  #   填了 → directSSH (原生 SSH + 固定 DNS + sshd:22222, 关 remoteAccess/SSM)
  #   留空 → remoteAccess (SSM sidecar, 老方式)
  local SSH_DOMAIN; SSH_DOMAIN="$(ctx directSshDomain)"
  local CONFIG
  if [ -n "$SSH_DOMAIN" ]; then
    echo "   模式=directSSH  domain=$SSH_DOMAIN  port=22222 (关 SSM)"
    CONFIG=$(cat <<JSON
{
  "jupyter-k8s": {"workspacePodWatching": {"enable": true}},
  "jupyter-k8s-aws-hyperpod": {
    "remoteAccess": {"enabled": false},
    "directSSH": {"enabled": true, "port": 22222, "domain": "$SSH_DOMAIN"}
  }
}
JSON
)
  else
    # ⭐ ${ACCOUNT} 整体赋值, 避开 zsh 吃 :role
    local SSM_NODE_ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/sagemaker-space-SSMManagedNode-$DATE"
    echo "   模式=remoteAccess(SSM)  ssmManagedNodeRole=$SSM_NODE_ROLE_ARN"
    CONFIG=$(cat <<JSON
{
  "jupyter-k8s": {"workspacePodWatching": {"enable": true}},
  "jupyter-k8s-aws-hyperpod": {
    "remoteAccess": {"enabled": true, "ssmManagedNodeRole": "$SSM_NODE_ROLE_ARN"}
  }
}
JSON
)
  fi
  # 目标版本: 两模式统一锁 v0.2.0 — WorkspaceIntegrationTemplate CRD (/dev/shm 档位
  # 注入依赖它, 见 dshm step) 只有 ≥v0.2.0 才有, 与连接方式无关。SPACES_ADDON_VERSION 可覆盖。
  # 从 0.1.x 升上来会因 controller-manager Deployment selector 不可变而 UPDATE_FAILED,
  # 由 _spaces_wait_update_or_fix 自愈 (删 controller Deployment 重试, 不动开发机 pod)。
  local WANT_VER="${SPACES_ADDON_VERSION:-v0.2.0-eksbuild.2}"

  # 探测当前是否已装 + 当前版本 (一次 describe 拿状态和版本)。
  local CUR_VER
  CUR_VER="$(aws eks describe-addon --cluster-name "$CLUSTER" --region "$REGION" \
    --addon-name amazon-sagemaker-spaces --query 'addon.addonVersion' --output text 2>/dev/null || true)"

  # 版本 flag: 仅在"想要的版本" != "当前版本"时带 --addon-version (避免对已达标的
  # addon 发无谓升级; 也避免 update 时重复指定同版本触发 No changes 误报)。
  # ⚠️ 只升不降: 若当前版本已 ≥ 想要的 (字典序足够, eksbuild 同族), 不带版本 flag。
  local VER_FLAG=()
  if [ -n "$WANT_VER" ] && [ "$CUR_VER" != "$WANT_VER" ]; then
    VER_FLAG=(--addon-version "$WANT_VER")
  fi

  if [ -n "$CUR_VER" ] && [ "$CUR_VER" != "None" ]; then
    # 已装 → update。区分三种结果: 成功 / 无变化(配置版本都没变) / 真失败。
    echo "   已装 (当前版本=$CUR_VER)${WANT_VER:+, 目标=$WANT_VER} → update"
    local OUT
    OUT="$(aws eks update-addon --cluster-name "$CLUSTER" --region "$REGION" \
      --addon-name amazon-sagemaker-spaces ${VER_FLAG[@]+"${VER_FLAG[@]}"} \
      --configuration-values "$CONFIG" --resolve-conflicts OVERWRITE 2>&1)" \
      && { echo "   ✓ 更新已提交"; _spaces_wait_update_or_fix; } \
      || { case "$OUT" in
             *"No changes"*|*"no changes"*) echo "   ✓ 配置/版本无变化, 跳过" ;;
             *) echo "   ⚠️ update 失败: $OUT" >&2 ;;
           esac; }
  else
    # 未装 → create (新装)。
    echo "   未装${WANT_VER:+, 目标版本=$WANT_VER} → create"
    aws eks create-addon --cluster-name "$CLUSTER" --region "$REGION" \
      --addon-name amazon-sagemaker-spaces ${VER_FLAG[@]+"${VER_FLAG[@]}"} \
      --configuration-values "$CONFIG" >/dev/null 2>&1 \
      && echo "   ✓ add-on 创建中" || echo "   ⚠️ create 失败" >&2
  fi
  echo "   等待 active (可能几分钟)..."
  aws eks wait addon-active --cluster-name "$CLUSTER" --region "$REGION" \
    --addon-name amazon-sagemaker-spaces && echo "   ✓ spaces add-on ACTIVE"

  # ⭐ add-on 每次升级/创建都会 re-apply seed, 把 WorkspaceTemplate 的
  # allowCustomImages / primaryStorage 冲回默认 (allowCustomImages 被冲回 false,
  # primaryStorage 被冲回 5Gi/1-100Gi)。这两项是 step_template 的 kubectl patch,
  # 非 add-on 期望状态, 故升级后必须立即重打 —— 否则只跑 spaces (如为 native SSH
  # 单独升级 add-on) 会漏补, 开发机默认盘退回 5Gi + BYOI 被关。收尾自动补一次;
  # 单独跑 template 步仍可用 (幂等)。
  echo "   → 收尾重打 WorkspaceTemplate (allowCustomImages/primaryStorage, 防升级冲刷)"
  step_template
}

# spaces update 是异步: 提交成功 ≠ 升级成功。v0.1.6→v0.1.7 改了
# jupyter-k8s-controller-manager 这个 Deployment 的 spec.selector.matchLabels,
# 而 K8s Deployment selector 不可变 → 原地升级被拒 (UPDATE_FAILED,
# UnsupportedAddonModification / field is immutable)。自愈: 删掉这个 controller
# Deployment (只是协调器, 不动正在跑的开发机 workspace pod), addon 会用新 selector
# 重建, 然后重跑一次 update。轮询升级结果, 命中此错才自愈, 只重试一次防死循环。
_spaces_wait_update_or_fix() {
  local ctl_deploy="jupyter-k8s-controller-manager"
  local ctl_ns="jupyter-k8s-system"
  local retried=0
  while :; do
    local st errmsg
    st="$(aws eks describe-addon --cluster-name "$CLUSTER" --region "$REGION" \
      --addon-name amazon-sagemaker-spaces --query 'addon.status' --output text 2>/dev/null)"
    case "$st" in
      ACTIVE) return 0 ;;
      CREATING|UPDATING|DEGRADED) sleep 8; continue ;;
      UPDATE_FAILED)
        # 拿失败详情: 最近一条 update 的 errors。
        local latest_update
        latest_update="$(aws eks list-updates --name "$CLUSTER" --region "$REGION" \
          --addon-name amazon-sagemaker-spaces --query 'updateIds[0]' --output text 2>/dev/null)"
        errmsg="$(aws eks describe-update --name "$CLUSTER" --region "$REGION" \
          --addon-name amazon-sagemaker-spaces --update-id "$latest_update" \
          --query 'update.errors[].errorMessage' --output text 2>/dev/null)"
        case "$errmsg" in
          *immutable*|*selector*|*UnsupportedAddonModification*)
            if [ "$retried" -eq 1 ]; then
              echo "   ⚠️ 已删 controller 重试仍失败: $errmsg" >&2; return 1
            fi
            echo "   ⚠️ 升级被拒 (selector 不可变)。删 $ctl_deploy 后重试 (不影响开发机 pod)..."
            kubectl delete deploy "$ctl_deploy" -n "$ctl_ns" --ignore-not-found >/dev/null 2>&1
            retried=1
            aws eks update-addon --cluster-name "$CLUSTER" --region "$REGION" \
              --addon-name amazon-sagemaker-spaces ${VER_FLAG[@]+"${VER_FLAG[@]}"} \
              --configuration-values "$CONFIG" --resolve-conflicts OVERWRITE >/dev/null 2>&1 \
              && echo "   ✓ 已删 controller, 重新提交 update" \
              || { echo "   ⚠️ 重新 update 提交失败" >&2; return 1; }
            sleep 8; continue ;;
          *)
            echo "   ⚠️ 升级失败 (非 selector 问题): $errmsg" >&2; return 1 ;;
        esac ;;
      *) sleep 8; continue ;;
    esac
  done
}

step_externaldns() {
  echo ">>> [externaldns] 开发机 directSSH: 私有 zone + external-dns role + add-on"
  local SSH_DOMAIN; SSH_DOMAIN="$(ctx directSshDomain)"
  if [ -z "$SSH_DOMAIN" ]; then
    echo "   (directSshDomain 未设, 跳过 — 未启用 directSSH)"; return
  fi
  need_cluster_arn
  local VPC_ID; VPC_ID="$(ctx vpcId)"
  : "${VPC_ID:?需要 vpcId (cdk.json)}"

  # ---- 1. Route53 私有 hosted zone (关联业务 VPC), 幂等 ----
  # zone/role 都在脚本自建 (不在 CDK): external-dns addon 装在 cdk deploy 之前,
  # 它依赖 role, role policy 又依赖 zone ARN → 三者必须都先于 CDK 建。照 step_ssm
  # 自建 role 的先例。域名须 == spaces directSSH.domain (两处同一 SSH_DOMAIN 变量)。
  local ZONE_ID
  ZONE_ID="$(aws route53 list-hosted-zones-by-name --dns-name "$SSH_DOMAIN" \
    --query "HostedZones[?Name=='${SSH_DOMAIN}.'].Id | [0]" --output text 2>/dev/null)"
  if [ -z "$ZONE_ID" ] || [ "$ZONE_ID" = "None" ]; then
    ZONE_ID="$(aws route53 create-hosted-zone --name "$SSH_DOMAIN" \
      --caller-reference "hyperpod-direct-ssh-$(date +%s)" \
      --hosted-zone-config Comment="HyperPod Spaces Direct SSH",PrivateZone=true \
      --vpc VPCRegion="$REGION",VPCId="$VPC_ID" \
      --query HostedZone.Id --output text 2>/dev/null)"
    echo "   ✓ 私有 zone 已建: $SSH_DOMAIN"
  else
    echo "   (私有 zone 已存在: $SSH_DOMAIN)"
  fi
  ZONE_ID="${ZONE_ID##*/}"   # 去掉 /hostedzone/ 前缀
  if [ -z "$ZONE_ID" ] || [ "$ZONE_ID" = "None" ]; then
    echo "   ❌ 取/建私有 zone 失败 (domain=$SSH_DOMAIN vpc=$VPC_ID)" >&2; return 1
  fi
  local ZONE_ARN="arn:aws:route53:::hostedzone/${ZONE_ID}"

  # ---- 2. external-dns Pod Identity role + zone 限定 policy, 幂等 ----
  # 信任 pods.eks.amazonaws.com (+ TagSession), SourceAccount/SourceArn 收窄到本集群。
  local DNS_ROLE="HpDsshExternalDns-${CLUSTER:0:40}"
  local DNS_ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${DNS_ROLE}"   # ⭐ 预拼避 zsh :role
  local TRUST; TRUST="$(cat <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"pods.eks.amazonaws.com"},"Action":["sts:AssumeRole","sts:TagSession"],"Condition":{"StringEquals":{"aws:SourceAccount":"$ACCOUNT","aws:SourceArn":"$CLUSTER_ARN"}}}]}
JSON
)"
  if aws iam create-role --role-name "$DNS_ROLE" \
       --assume-role-policy-document "$TRUST" >/dev/null 2>&1; then
    echo "   ✓ role 已建: $DNS_ROLE"
  else
    aws iam update-assume-role-policy --role-name "$DNS_ROLE" --policy-document "$TRUST" >/dev/null 2>&1 || true
    echo "   (role 已存在, trust 已更新: $DNS_ROLE)"
  fi
  # 只允许改这一个 zone 的记录 (+ 全局 ListHostedZones 供发现)。inline policy 整体覆盖。
  aws iam put-role-policy --role-name "$DNS_ROLE" --policy-name HpDsshRoute53 \
    --policy-document "$(cat <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["route53:ChangeResourceRecordSets","route53:ListResourceRecordSets"],"Resource":"$ZONE_ARN"},{"Effect":"Allow","Action":["route53:ListHostedZones"],"Resource":"*"}]}
JSON
)" >/dev/null 2>&1
  echo "   ✓ zone 限定 policy 已挂 (zone=$ZONE_ID)"
  local ROLE_ARN="$DNS_ROLE_ARN"

  echo "   role=$ROLE_ARN  domain=$SSH_DOMAIN"
  # ---- 3. external-dns addon ----
  # sources=[service]: 只看 SSH headless Service 的 hostname 注解; domainFilters
  # 锁死域名 (须 == spaces directSSH.domain); TXT registry 标所有权。
  local CONFIG; CONFIG=$(cat <<JSON
{
  "sources": ["service"],
  "domainFilters": ["$SSH_DOMAIN"],
  "policy": "sync",
  "registry": "txt",
  "txtOwnerId": "$CLUSTER-direct-ssh",
  "triggerLoopOnEvent": true,
  "interval": "15s"
}
JSON
)
  local PODID; PODID=$(cat <<JSON
[{"serviceAccount": "external-dns", "roleArn": "$ROLE_ARN"}]
JSON
)
  # 版本可 env 覆盖 (EXTERNAL_DNS_ADDON_VERSION), 默认 POC 验证过的版本。
  local WANT_VER="${EXTERNAL_DNS_ADDON_VERSION:-v0.21.0-eksbuild.5}"
  local CUR_VER
  CUR_VER="$(aws eks describe-addon --cluster-name "$CLUSTER" --region "$REGION" \
    --addon-name external-dns --query 'addon.addonVersion' --output text 2>/dev/null || true)"
  # 仅在版本不一致时带 --addon-version (避免重复指定同版本触发 No changes 误报)。
  local VER_FLAG=()
  [ "$CUR_VER" != "$WANT_VER" ] && VER_FLAG=(--addon-version "$WANT_VER")

  if [ -n "$CUR_VER" ] && [ "$CUR_VER" != "None" ]; then
    echo "   已装 (当前版本=$CUR_VER, 目标=$WANT_VER) → update"
    local OUT
    OUT="$(aws eks update-addon --cluster-name "$CLUSTER" --region "$REGION" \
      --addon-name external-dns ${VER_FLAG[@]+"${VER_FLAG[@]}"} \
      --configuration-values "$CONFIG" \
      --pod-identity-associations "$PODID" --resolve-conflicts OVERWRITE 2>&1)" \
      && echo "   ✓ 更新已提交" \
      || { case "$OUT" in
             *"No changes"*|*"no changes"*) echo "   ✓ 配置/版本无变化, 跳过" ;;
             *) echo "   ⚠️ update 失败: $OUT" >&2 ;;
           esac; }
  else
    echo "   未装 (目标版本=$WANT_VER) → create"
    aws eks create-addon --cluster-name "$CLUSTER" --region "$REGION" \
      --addon-name external-dns --addon-version "$WANT_VER" \
      --configuration-values "$CONFIG" \
      --pod-identity-associations "$PODID" --resolve-conflicts OVERWRITE >/dev/null 2>&1 \
      && echo "   ✓ add-on 创建中" || echo "   ⚠️ create 失败" >&2
  fi
  aws eks wait addon-active --cluster-name "$CLUSTER" --region "$REGION" \
    --addon-name external-dns && echo "   ✓ external-dns add-on ACTIVE"
}

step_logging() {
  echo ">>> [logging] §4.1d 开容器日志 → CloudWatch (走 add-on configurationValues)"
  # ⭐ 必须改 add-on 的 configurationValues (不是 patch ObservabilityConfig CR)!
  # observability add-on 管理该 CR: 直接 kubectl patch CR 的 spec.enableLogging=true,
  # 会被 add-on 下次 reconcile (版本升级 / 控制台改配 / 周期性同步) 用它自己期望的
  # 默认值 (logging.enabled=false) 覆盖冲掉 → logging 被悄悄关掉 (实测踩坑 2026-07-21)。
  # 正确做法: 把 metricsProvider.logging.enabled=true 写进 add-on configurationValues,
  # 成为 add-on 的"期望状态", reconcile 不再冲。字段路径 = metricsProvider.logging.enabled。
  local ADDON=amazon-sagemaker-hyperpod-observability
  # 现有 config 存在则不存在 → 提示 (add-on 没装)
  local cur
  cur="$(aws eks describe-addon --cluster-name "$CLUSTER" --region "$REGION" \
    --addon-name "$ADDON" --query 'addon.configurationValues' --output text 2>/dev/null || true)"
  if [ -z "$cur" ] || [ "$cur" = "None" ]; then
    echo "   ⚠️ 取不到 $ADDON 的 configurationValues (add-on 没装好?), 稍后重跑本步" >&2
    return
  fi
  # update-addon 会整体替换 configurationValues → 必须读现有 config, 只把 logging.enabled
  # 置 true, 其余 (ampWorkspace/metricsProvider 各项) 原样保留, 再整体写回。用 python 合并。
  local merged
  merged="$(python3 -c "
import json,sys
c=json.loads('''$cur''')
c.setdefault('metricsProvider',{}).setdefault('logging',{})['enabled']=True
print(json.dumps(c))
" 2>/dev/null)"
  if [ -z "$merged" ]; then
    echo "   ⚠️ 合并 configurationValues 失败, 跳过 (现有配置: ${cur:0:80}...)" >&2
    return
  fi
  aws eks update-addon --cluster-name "$CLUSTER" --region "$REGION" \
    --addon-name "$ADDON" --configuration-values "$merged" \
    --resolve-conflicts OVERWRITE >/dev/null
  echo "   ✓ 已提交 logging.enabled=true 到 add-on config (operator 约 1 分钟拉起 fluent-bit)"
  echo "   验证: kubectl get ds -n hyperpod-observability | grep fluent-bit"
}

step_template() {
  echo ">>> [template] §4.2 两个 WorkspaceTemplate 开 allowCustomImages + 调 EBS 默认/上限"
  # WorkspaceTemplate 是【业务集群】资源。先切 kubeconfig + 所有 kubectl 带 --context,
  # 避免单独跑本步时 patch 到当前 (可能是平台) 集群。
  aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION" --alias "$CLUSTER" >/dev/null
  kubectl --context "$CLUSTER" get workspacetemplate -n jupyter-k8s-system \
    -o jsonpath='{range .items[*]}{.metadata.name}{"  allowCustomImages="}{.spec.allowCustomImages}{"\n"}{end}' 2>/dev/null || {
      echo "   ⚠️ 取不到 workspacetemplate (spaces 还没 seed 完?), 稍后重跑本步" >&2; return; }
  local t
  for t in sagemaker-jupyter-template sagemaker-code-editor-template; do
    kubectl --context "$CLUSTER" patch workspacetemplate "$t" -n jupyter-k8s-system \
      --type merge -p '{"spec":{"allowCustomImages":true}}' >/dev/null 2>&1 \
      && echo "   ✓ $t allowCustomImages=true" \
      || echo "   (跳过 $t: 不存在或已是 true)"
    # 开发机主目录 /home/sagemaker-user EBS 默认/范围: spaces add-on seed 出来是
    # 5Gi/1-100Gi, 太小 (装 conda/深度学习环境就满)。抬到默认 100Gi, 范围 10-500Gi。
    kubectl --context "$CLUSTER" patch workspacetemplate "$t" -n jupyter-k8s-system \
      --type merge -p '{"spec":{"primaryStorage":{"defaultSize":"100Gi","minSize":"10Gi","maxSize":"500Gi"}}}' >/dev/null 2>&1 \
      && echo "   ✓ $t primaryStorage 默认 100Gi / 范围 10-500Gi" \
      || echo "   (跳过 $t primaryStorage: 不存在)"
  done
}

step_fsxadmin() {
  echo ">>> [fsxadmin] §4.4 fsx-admin pod (多 FSx: 一个 pod 挂多块盘到 /fsx-mnt/<fs-id>)"
  # 多 FSx: 从 cdk.json platformFsxFilesystems (逗号分隔 fs-id) 读盘列表, 一个
  # fsx-admin pod 挂所有盘, 每块到 /fsx-mnt/<fs-id> (中性父目录, 不嵌套某块盘根)。
  # 兼容旧格式 fs-id:别名 (取冒号前 fs-id, 忽略别名段)。
  # ⚠️ FSx 必须 Lustre 2.15 (2.12 不支持 project quota)。
  local FS_LIST; FS_LIST="$(ctx platformFsxFilesystems)"
  if [ -z "$FS_LIST" ]; then
    echo "   ⚠️ cdk.json platformFsxFilesystems 未配, 跳过 (格式 fs-id,fs-id2)" >&2
    return
  fi
  aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION" --alias "$CLUSTER" >/dev/null

  # 逐块盘生成 PV+PVC (静态绑定), 收集 volumeMounts/volumes 片段拼进 Deployment。
  local pvs="" mounts="" volumes="" fsid_re='^fs-[0-9a-f]+$'
  local IFS_SAVE="$IFS"; IFS=','
  for entry in $FS_LIST; do
    IFS="$IFS_SAVE"
    entry="$(echo "$entry" | xargs)"   # trim
    [ -z "$entry" ] && { IFS=','; continue; }
    local fs_id="${entry%%:*}"         # 兼容旧 fs-id:别名, 只取 fs-id
    if ! echo "$fs_id" | grep -qE "$fsid_re"; then
      echo "   ❌ fs-id 非法 (需 fs-<hex>): $fs_id" >&2; IFS=','; continue
    fi
    local dns mount
    read -r dns mount < <(aws fsx describe-file-systems --file-system-ids "$fs_id" --region "$REGION" \
      --query "FileSystems[0].[DNSName,LustreConfiguration.MountName]" --output text 2>/dev/null)
    if [ -z "$dns" ] || [ "$dns" = "None" ]; then
      echo "   ❌ 取不到 FSx $fs_id 的 DNS/MountName, 跳过" >&2; IFS=','; continue
    fi
    echo "   $fs_id → /fsx-mnt/$fs_id (dns=$dns mount=$mount)"
    pvs="$pvs$(cat <<YAML
---
apiVersion: v1
kind: PersistentVolume
metadata: { name: fsx-admin-pv-$fs_id, labels: { app: fsx-admin, fsxid: "$fs_id" } }
spec:
  capacity: { storage: 1200Gi }
  volumeMode: Filesystem
  accessModes: [ReadWriteMany]
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ""
  csi:
    driver: fsx.csi.aws.com
    volumeHandle: $fs_id-fsxadmin
    volumeAttributes: { dnsname: "$dns", mountname: "$mount" }
  claimRef: { namespace: hyperpod-platform-system, name: fsx-admin-pvc-$fs_id }
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: fsx-admin-pvc-$fs_id, namespace: hyperpod-platform-system, labels: { app: fsx-admin, fsxid: "$fs_id" } }
spec:
  accessModes: [ReadWriteMany]
  storageClassName: ""
  resources: { requests: { storage: 1200Gi } }
  volumeName: fsx-admin-pv-$fs_id
YAML
)
"
    mounts="$mounts        - { name: $fs_id, mountPath: /fsx-mnt/$fs_id }
"
    volumes="$volumes      - { name: $fs_id, persistentVolumeClaim: { claimName: fsx-admin-pvc-$fs_id } }
"
    IFS=','
  done
  IFS="$IFS_SAVE"

  if [ -z "$mounts" ]; then
    echo "   ❌ 没有有效 FSx 条目, 中止" >&2; return 1
  fi

  # Deployment: 一个 fsx-admin pod, 挂上面所有盘。
  local deploy; deploy="$(cat <<YAML
---
apiVersion: apps/v1
kind: Deployment
metadata: { name: fsx-admin, namespace: hyperpod-platform-system, labels: { app: fsx-admin } }
spec:
  replicas: 1
  selector: { matchLabels: { app: fsx-admin } }
  template:
    metadata: { labels: { app: fsx-admin } }
    spec:
      containers:
      - name: sh
        image: public.ecr.aws/amazonlinux/amazonlinux:2023
        command: ["sh", "-c", "dnf install -y lustre-client && sleep infinity"]
        securityContext: { capabilities: { add: ["SYS_ADMIN"] } }
        resources:
          requests: { cpu: "10m", memory: "64Mi" }
          limits:   { cpu: "500m", memory: "1Gi" }
        volumeMounts:
$mounts      volumes:
$volumes
YAML
)"

  # namespace (幂等)。
  kubectl --context "$CLUSTER" create namespace hyperpod-platform-system >/dev/null 2>&1 || true
  # PV/PVC: apply 幂等 (各自独立资源, 无合并残留问题)。
  printf '%s\n' "$pvs" | kubectl --context "$CLUSTER" apply -f -
  # Deployment: 先删后建, 不用 apply。
  # ⚠️ apply 对 Deployment 的 volumeMounts/volumes 是三方合并 —— 改盘列表 (去掉一块盘)
  # 时旧的 volumeMount 不会被移除, 残留挂载 (指向已删 PVC) 会让 pod 重建失败。删后重建
  # 保证 pod 挂载 == 当前盘列表, 无残留。删 Deployment 只重建协调 pod, 不动 FSx 数据/开发机。
  kubectl --context "$CLUSTER" -n hyperpod-platform-system delete deploy fsx-admin --ignore-not-found >/dev/null 2>&1
  printf '%s\n' "$deploy" | kubectl --context "$CLUSTER" apply -f -
  kubectl --context "$CLUSTER" -n hyperpod-platform-system rollout status deploy/fsx-admin
  kubectl --context "$CLUSTER" -n hyperpod-platform-system exec deploy/fsx-admin -- ls /fsx-mnt \
    && echo "   ✓ fsx-admin 能列出 /fsx-mnt (各盘子目录)"
}

step_lws() {
  echo ">>> [lws] LeaderWorkerSet (多机 gang 原语) + task-governance VAP 窄豁免"
  # 背景: llm-d 多机推理用 LWS 官方多机 gang; 平台 Go controller 也
  # watch LeaderWorkerSet CRD (缺 CRD → controller create manager 失败 CrashLoop)。
  # 故 LWS 是集群级前置, 装在业务集群 (推理 pod + controller watch 所在)。
  local LWS_VERSION="${LWS_VERSION:-0.9.0}"
  # kubeconfig 就绪 (幂等, 用集群名作 context 别名跟其它 kubectl 步骤一致)。
  aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION" --alias "$CLUSTER" >/dev/null 2>&1 || true

  # ---- ① 装 LWS (helm OCI chart, --wait 等 controller ready; 幂等 upgrade --install) ----
  echo "   装 LWS v$LWS_VERSION (helm oci, ns=lws-system)..."
  helm --kube-context "$CLUSTER" upgrade --install lws \
    oci://registry.k8s.io/lws/charts/lws \
    --namespace lws-system --create-namespace --version "$LWS_VERSION" \
    --wait --timeout 5m >/dev/null 2>&1 \
    && echo "   ✓ LWS release deployed" \
    || { echo "   ⚠️ helm 装 LWS 失败 (检查 helm/网络/凭证)" >&2; return 1; }
  # 校验 CRD + controller
  if kubectl --context "$CLUSTER" get crd leaderworkersets.leaderworkerset.x-k8s.io >/dev/null 2>&1; then
    echo "   ✓ CRD leaderworkersets.leaderworkerset.x-k8s.io 存在"
  else
    echo "   ⚠️ LWS CRD 未建出" >&2; return 1
  fi
  kubectl --context "$CLUSTER" -n lws-system rollout status deploy/lws-controller-manager \
    --timeout=120s >/dev/null 2>&1 && echo "   ✓ lws-controller-manager ready"

  # ---- ② task-governance VAP 窄豁免: 放行 LWS-owned StatefulSet (幂等) ----
  # 为什么: LWS v0.9.0 派生的 StatefulSet 不继承 queue-name label, HyperPod
  # task-governance VAP 拦每个 sts 要 queue-name → LWS sts 建不出。只豁免
  # owner 是 LeaderWorkerSet / Pod 的 sts, 不放宽其它。
  # ⚠️ 改的是集群共享 VAP, 爆炸半径全平台 — 生产走变更评审。
  local VAP="hyperpod-task-governance-admission-policy"
  if ! kubectl --context "$CLUSTER" get validatingadmissionpolicy "$VAP" >/dev/null 2>&1; then
    echo "   (VAP $VAP 不存在, 跳过豁免 — 无 task-governance 的集群无需)"
    return
  fi
  if kubectl --context "$CLUSTER" get validatingadmissionpolicy "$VAP" -o json \
       | jq -e '.spec.matchConditions[]? | select(.name=="exclude-lws-owned-statefulsets")' >/dev/null 2>&1; then
    echo "   (VAP 豁免 exclude-lws-owned-statefulsets 已存在, 跳过)"
  else
    kubectl --context "$CLUSTER" patch validatingadmissionpolicy "$VAP" --type=json -p \
      '[{"op":"add","path":"/spec/matchConditions/-","value":{
        "name":"exclude-lws-owned-statefulsets",
        "expression":"!(object.kind == \"StatefulSet\" && has(object.metadata.ownerReferences) && object.metadata.ownerReferences.exists(ref, (ref.kind == \"LeaderWorkerSet\" && ref.apiVersion.startsWith(\"leaderworkerset.x-k8s.io/\")) || (ref.kind == \"Pod\" && ref.apiVersion == \"v1\")))"
      }}]' >/dev/null 2>&1 \
      && echo "   ✓ VAP 已加豁免 exclude-lws-owned-statefulsets (爆炸半径全平台, 生产须评审)" \
      || echo "   ⚠️ VAP patch 失败" >&2
  fi
}

# EC2 部署机: 先放行本机 → 业务集群 SG 443 (任何 kubectl 步骤前), 否则 private endpoint 连不上
ensure_ec2_sg_access

for step in "${STEPS[@]}"; do
  echo
  case "$step" in
    verify) step_verify ;;
    ebs) step_ebs ;;
    ssm) step_ssm ;;
    pd) step_pd ;;
    spaces) step_spaces ;;
    externaldns) step_externaldns ;;
    logging) step_logging ;;
    template) step_template ;;
    fsxadmin) step_fsxadmin ;;
    lws) step_lws ;;
    *) echo "❌ 未知步骤 '$step' (可选: verify|ebs|ssm|pd|spaces|externaldns|logging|template|fsxadmin|lws)" >&2; exit 1 ;;
  esac
done

echo
echo "============================================================"
echo ">> Prerequisites 完成。接下来:"
echo "   - 若 spaces 刚装完, 等 1-2 分钟再跑 './deploy/cluster-prereq.sh template' 确保 seed 完"
echo "============================================================"
