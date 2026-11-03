#!/usr/bin/env sh
# ECS 容器入口: 生成 kubeconfig → 跑 informer worker。
#
# 为什么要生成 kubeconfig: worker 通过 kubernetes-asyncio 的 load_kube_config()
# 读 ~/.kube/config, 其中 exec 段调 `aws eks get-token` 拿 apiserver token。
# ECS 容器里没有 kubeconfig, 所以启动时用 task role 的 AWS 凭证现生成一个。
#
# task role 必须: (a) 有 eks:DescribeCluster (update-kubeconfig 要读 endpoint+CA);
#                 (b) 在目标 EKS 上有 access entry (apiserver 才认这个 IAM 身份)。
set -eu

: "${AWS_REGION:?AWS_REGION 必填}"
: "${EKS_CLUSTER_NAME:?EKS_CLUSTER_NAME 必填}"

echo "[entrypoint] update-kubeconfig cluster=${EKS_CLUSTER_NAME} region=${AWS_REGION}"
aws eks update-kubeconfig \
    --name "${EKS_CLUSTER_NAME}" \
    --region "${AWS_REGION}"

echo "[entrypoint] starting worker"
exec python -m worker.main
