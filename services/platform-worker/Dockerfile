# platform-worker 镜像 · K8s informer worker (CR → DDB)
#
# ⚠️ build context 必须是 services/ (不是 platform-worker/), 因为 worker 依赖
#    platform-api 的源码 (import app.*)。两个目录都要进 context:
#
#    docker build -f platform-worker/Dockerfile -t platform-worker:dev services/
#    (在仓库根: docker build -f services/platform-worker/Dockerfile -t platform-worker:dev services/)
#
# 运行时需要 aws CLI: entrypoint 用 `aws eks update-kubeconfig` 生成 kubeconfig,
# 且 kubeconfig 里的 exec 插件会调 `aws eks get-token` 拿 apiserver bearer token。

FROM python:3.11-slim AS base

# 中国网络兼容 (跟 operators/Dockerfile 一致的思路); 生产可注释掉换默认源。
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# aws CLI v2 binary (kubeconfig exec 拿 token 用)。用 v2 独立打包而非 pip awscli v1,
# 避免 awscli 的 botocore pin 跟 worker 依赖的 aioboto3 版本冲突 (与 api 镜像一致)。
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip ca-certificates \
    && curl -sSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/aws /tmp/awscliv2.zip \
    && apt-get purge -y unzip \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# 先装 platform-api (worker 的 path 依赖), 再装 worker 本体。
# 分两层 COPY 利用 layer cache: 依赖不变时不重装。
COPY platform-api/ /srv/platform-api/
RUN pip install --no-cache-dir /srv/platform-api

COPY platform-worker/ /srv/platform-worker/
RUN pip install --no-cache-dir /srv/platform-worker

# entrypoint: 先生成 kubeconfig, 再跑 worker。
ENTRYPOINT ["/srv/platform-worker/entrypoint.sh"]
