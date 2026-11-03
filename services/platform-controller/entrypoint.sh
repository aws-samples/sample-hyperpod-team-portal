#!/usr/bin/env sh
# 容器入口: 生成"业务集群"kubeconfig → 跑 controller。
#
# 跨集群模型 (与 Python worker 的单集群不同):
#   - 业务集群 (集群 Y, watch CR/Workload/Pod): 用 BUSINESS_EKS_CLUSTER_NAME
#     现生成 kubeconfig。kubeconfig 的 exec 段调 `aws eks get-token`, client-go
#     据此自动刷新 apiserver token (15min 过期前, 不撞 401)。
#   - 平台集群 (集群 X, controller 所在, leader election lease 放这): 不生成 kubeconfig,
#     PLATFORM_KUBECONFIG 留空 → 代码走 in-cluster config (用 Pod 的 ServiceAccount token)。
#
# 运行的 IAM 身份 (Pod Identity / IRSA) 必须:
#   (a) eks:DescribeCluster 于业务集群 (update-kubeconfig 读 endpoint+CA);
#   (b) 在业务集群有 access entry (apiserver 认这个 IAM 身份 → 映射到 RBAC group);
#   (c) DynamoDB 读写权限 (投影写 DDB)。
# 见 docs/controller-deployment.md。
set -eu

: "${AWS_REGION:?AWS_REGION 必填}"
: "${BUSINESS_EKS_CLUSTER_NAME:?BUSINESS_EKS_CLUSTER_NAME 必填 (业务集群名, watch 目标)}"

# 生成业务集群 kubeconfig 到固定路径, 供 BUSINESS_KUBECONFIG 指向。
BUSINESS_KUBECONFIG="${BUSINESS_KUBECONFIG:-${HOME}/.kube/business-config}"
export BUSINESS_KUBECONFIG

echo "[entrypoint] update-kubeconfig cluster=${BUSINESS_EKS_CLUSTER_NAME} region=${AWS_REGION} → ${BUSINESS_KUBECONFIG}"
aws eks update-kubeconfig \
    --name "${BUSINESS_EKS_CLUSTER_NAME}" \
    --region "${AWS_REGION}" \
    --kubeconfig "${BUSINESS_KUBECONFIG}"

# PLATFORM_KUBECONFIG 留空 → in-cluster (平台集群 SA)。leader election lease 放平台集群。
echo "[entrypoint] starting controller (business=${BUSINESS_EKS_CLUSTER_NAME}, platform=in-cluster)"
exec /usr/local/bin/controller
