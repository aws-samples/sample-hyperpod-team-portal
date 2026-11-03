#!/usr/bin/env bash
#
# 集群一次性初始化 (装一次, 不随每次部署变):
#   1. kubeconfig            → 两集群 update-kubeconfig --alias (后面步骤的前提)
#   2. access entry          → 把当前 IAM 身份加进平台集群 (否则 kubectl 报 credentials)
#   3. ALB Controller        → 平台集群 (helm)
#   4. rbac                  → 业务集群 ClusterRole+Binding (platform-api-manager)
#   5. kuberay               → 业务集群 KubeRay operator (helm) — RayJob 前置依赖
#
# 注: KubeRay operator 是 RayJob (Ray 训练) 的运行前提, 装在业务集群 (RayJob CR 下发到
#     业务集群, Kueue/节点也在那)。SageMaker/HyperPod 无官方 KubeRay add-on, 只能自装;
#     官方分发即 helm chart。v1.6.2 原生集成 Kueue (rayjob-kueue-controller), 无需额外装。
#     不装则平台的 RayJob 功能全部起不来 (CR 建了没 operator 处理)。
#
# 注: 优先级档 (WorkloadPriorityClass) 不再由本脚本初始化 — 已迁移到 SageMaker
#     HyperPod task governance (cluster policy)。新装需在 AWS Console 的 cluster policy
#     补建 common 档; 更新装先删旧自建 WPC 再在平台 UI 建。
#     见 deploy/k8s/workload-priority-classes.yaml 文件头说明。
#
# 注: Prefix Delegation + maxpods-patcher 已移到 cluster-prereq.sh 的 pd 步骤
#     (必须在装 spaces 之前抬 maxPods, 否则 spaces DEGRADED), 本脚本不再含。
#
# 自动从 infrastructure/cdk.json 读 project/region/account/集群名。
# 跨集群: 平台集群 = {project}-{platformClusterSuffix}, 业务集群 = businessClusterName。
# 单集群: 两者同名时全装一个集群。
#
# 注: fsx-admin pod 不在此脚本管 (单独/手动建, 见 deployment-guideline.md §4.3)。
#
# 用法:
#   ./deploy/cluster-init.sh                  # 全部 (kube + access + alb + rbac + kuberay)
#   ./deploy/cluster-init.sh access           # 只给当前身份加平台集群 access entry
#   ./deploy/cluster-init.sh alb rbac         # 跳过前置 (已就绪时)
#   ./deploy/cluster-init.sh kuberay          # 只装 KubeRay operator (补 RayJob 依赖)
#
# 前提: CDK 已 deploy (集群 + Pod Identity + access entry); helm / kubectl / aws 可用;
#       凭证就绪 (如 AWS_PROFILE=xxx)。kubeconfig + 自身 access entry 本脚本自动搞定。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CDK_JSON="$ROOT/infrastructure/cdk.json"

ctx() { python3 -c "import json,sys; print(json.load(open('$CDK_JSON'))['context'].get('$1',''))"; }
PROJECT="$(ctx projectName)"
REGION="$(ctx region)"
VPC_ID="$(ctx vpcId)"
PLATFORM_CLUSTER="${PROJECT}-$(ctx platformClusterSuffix)"
BUSINESS_CLUSTER="$(ctx businessClusterName)"

# context 名 = update-kubeconfig --alias 用的简短名 (= 集群名)
PLATFORM_CTX="${PLATFORM_CONTEXT:-$PLATFORM_CLUSTER}"
BUSINESS_CTX="${BUSINESS_CONTEXT:-$BUSINESS_CLUSTER}"

TARGETS=("$@")
[ ${#TARGETS[@]} -eq 0 ] && TARGETS=(kube access alb rbac kuberay)

echo ">> PROJECT=$PROJECT REGION=$REGION"
echo "   平台集群=$PLATFORM_CLUSTER (ctx=$PLATFORM_CTX)  业务集群=$BUSINESS_CLUSTER (ctx=$BUSINESS_CTX)"
echo "   targets=${TARGETS[*]}"

init_kube() {
  echo ">> [1/4] kubeconfig → 两集群 (--alias 简短名, 后面步骤的前提)"
  # 平台集群 (manifest apply 目标)
  aws eks update-kubeconfig --name "$PLATFORM_CLUSTER" --region "$REGION" \
    --alias "$PLATFORM_CTX" >/dev/null
  echo "   ✓ 平台集群 context=$PLATFORM_CTX"
  # 业务集群 (跨集群操作目标); 单集群时与平台同名, 跳过避免重复
  if [ "$BUSINESS_CLUSTER" != "$PLATFORM_CLUSTER" ]; then
    aws eks update-kubeconfig --name "$BUSINESS_CLUSTER" --region "$REGION" \
      --alias "$BUSINESS_CTX" >/dev/null
    echo "   ✓ 业务集群 context=$BUSINESS_CTX"
  fi
}

init_access() {
  echo ">> [2/4] access entry → 把当前 IAM 身份加进平台集群 $PLATFORM_CLUSTER"
  # 取当前身份, 把 STS assumed-role ARN 还原成底层 role ARN (access entry 要 role ARN)
  local caller acct role_arn
  caller="$(aws sts get-caller-identity --query Arn --output text)"
  acct="$(aws sts get-caller-identity --query Account --output text)"
  if echo "$caller" | grep -q ":assumed-role/"; then
    local rn; rn="$(echo "$caller" | sed -E 's|.*:assumed-role/([^/]+)/.*|\1|')"
    role_arn="arn:aws:iam::${acct}:role/${rn}"
  else
    role_arn="$caller"   # IAM user / 已是 role ARN
  fi
  echo "   principal=$role_arn"
  # 建 access entry (已存在则忽略)
  aws eks create-access-entry --cluster-name "$PLATFORM_CLUSTER" --region "$REGION" \
    --principal-arn "$role_arn" >/dev/null 2>&1 \
    && echo "   ✓ access entry 已建" \
    || echo "   (access entry 已存在, 跳过)"
  # 关联 ClusterAdmin policy (幂等)
  aws eks associate-access-policy --cluster-name "$PLATFORM_CLUSTER" --region "$REGION" \
    --principal-arn "$role_arn" \
    --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \
    --access-scope type=cluster >/dev/null 2>&1 \
    && echo "   ✓ ClusterAdmin policy 已关联" \
    || echo "   (policy 已关联, 跳过)"
  echo "   access entry 生效有几秒延迟, 后续 kubectl 若仍 401 稍等重试"

  # ---- 网络: 在 EC2 部署机上跑时, 放行本机 SG → 平台集群 SG 的 443 ----
  # access entry 只解决"身份被集群认" (否则 401); 但 EC2 连 private endpoint 还需 SG 放行,
  # 否则 kubectl/helm 连 API server i/o timeout。仅 EC2 上 (IMDS 可达) 自动做; mac/本地跳过。
  local token imds_iid ec2_sg cluster_sg
  token="$(curl -s -m 2 -X PUT 'http://169.254.169.254/latest/api/token' \
            -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null || true)"
  imds_iid="$(curl -s -m 2 -H "X-aws-ec2-metadata-token: $token" \
            http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || true)"
  if [ -z "$imds_iid" ]; then
    echo "   (非 EC2 上跑, 跳过 SG 放行; 本地/VPN 连集群请自行确保网络可达)"
    return 0
  fi
  ec2_sg="$(aws ec2 describe-instances --region "$REGION" --instance-ids "$imds_iid" \
    --query 'Reservations[0].Instances[0].NetworkInterfaces[0].Groups[0].GroupId' --output text 2>/dev/null)"
  cluster_sg="$(aws eks describe-cluster --name "$PLATFORM_CLUSTER" --region "$REGION" \
    --query 'cluster.resourcesVpcConfig.clusterSecurityGroupId' --output text 2>/dev/null)"
  if [ -n "$ec2_sg" ] && [ "$ec2_sg" != "None" ] && [ -n "$cluster_sg" ] && [ "$cluster_sg" != "None" ]; then
    if aws ec2 authorize-security-group-ingress --region "$REGION" \
         --group-id "$cluster_sg" --protocol tcp --port 443 --source-group "$ec2_sg" >/dev/null 2>&1; then
      echo "   ✓ 已放行 EC2 SG($ec2_sg) → 平台集群 SG($cluster_sg) 443"
    else
      echo "   (SG 443 规则已存在或无需改, 跳过: $ec2_sg → $cluster_sg)"
    fi
  else
    echo "   ⚠️ 取 EC2/集群 SG 失败, 跳过 SG 放行 (ec2_sg=$ec2_sg cluster_sg=$cluster_sg)" >&2
  fi
}

init_alb() {
  echo ">> [3/4] ALB Controller → 平台集群 $PLATFORM_CTX"
  helm repo add eks https://aws.github.io/eks-charts >/dev/null 2>&1 || true
  helm repo update eks >/dev/null
  # SA 的 IAM 权限走 CDK 建的 Pod Identity association (不配 IRSA)
  helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
    -n kube-system \
    --kube-context "$PLATFORM_CTX" \
    --set clusterName="$PLATFORM_CLUSTER" \
    --set serviceAccount.create=true \
    --set serviceAccount.name=aws-load-balancer-controller \
    --set region="$REGION" \
    --set vpcId="$VPC_ID"
  kubectl --context "$PLATFORM_CTX" -n kube-system rollout status deploy/aws-load-balancer-controller
}

init_rbac() {
  # 业务集群 ClusterRole + Binding (替代 access entry 的 ClusterAdminPolicy)。
  # access entry 只映射 cluster-workspace-admin group, 真正权限靠这个 ClusterRole。
  # ⚠️ 必须在后端 pod 操作业务集群之前 apply, 否则 api 操作 → 403。
  echo ">> 业务集群 RBAC (platform-api-manager ClusterRole) → $BUSINESS_CTX"
  kubectl --context "$BUSINESS_CTX" apply -f "$ROOT/deploy/k8s/business-cluster-rbac.yaml"
}

init_kuberay() {
  # RayJob 前置依赖: KubeRay operator。装在业务集群 (RayJob CR/pod/Kueue 都在那)。
  # 版本 pin: v1.6.2 原生集成 Kueue (rayjob-kueue-controller), 可 KUBERAY_VERSION 覆盖。
  echo ">> KubeRay operator (RayJob 依赖) → 业务集群 $BUSINESS_CTX"
  helm repo add kuberay https://ray-project.github.io/kuberay-helm/ >/dev/null 2>&1 || true
  helm repo update kuberay >/dev/null
  helm upgrade --install kuberay-operator kuberay/kuberay-operator \
    --version "${KUBERAY_VERSION:-1.6.2}" \
    -n kuberay --create-namespace \
    --kube-context "$BUSINESS_CTX"
  kubectl --context "$BUSINESS_CTX" -n kuberay rollout status deploy/kuberay-operator
}

for t in "${TARGETS[@]}"; do
  case "$t" in
    kube)    init_kube ;;
    access)  init_access ;;
    alb)     init_alb ;;
    rbac)    init_rbac ;;
    kuberay) init_kuberay ;;
    *) echo "❌ 未知 target: $t (可选 kube|access|alb|rbac|kuberay)" >&2; exit 1 ;;
  esac
done

echo ">> 集群初始化完成. 接下来: ./deploy/build-push.sh && ./deploy/render-and-apply.sh"
