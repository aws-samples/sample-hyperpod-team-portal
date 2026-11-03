# platform-api 后端镜像 (生产跑 EKS CPU node group).
#   - 依赖走 pyproject.toml (setuptools), pip install .
#   - in-cluster K8s config (KUBERNETES_SERVICE_HOST 自动注入)
#   - AWS 凭证走 EKS Pod Identity (AWS_PROFILE / DDB_ENDPOINT_URL 留空)
#   - 跨集群: 业务集群 kubeconfig 是 exec 模式 (aws eks get-token), 需要 aws CLI。
#     用 v2 binary (独立打包, 不依赖系统 botocore, 避免与 aioboto3 版本冲突)。
FROM public.ecr.aws/docker/library/python:3.12-slim

# aws CLI v2 (跨集群 kubeconfig exec 拿 token 用)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip ca-certificates \
    && curl -sSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/aws /tmp/awscliv2.zip \
    && apt-get purge -y unzip \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先拷依赖声明 + 源码 (setuptools find packages 需要 app/ 在场才能 install)
COPY pyproject.toml ./
COPY app/ ./app/
COPY scripts/ ./scripts/

# 装运行依赖 (不含 dev/test 可选组)
RUN pip install --no-cache-dir .

EXPOSE 8800

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8800"]
