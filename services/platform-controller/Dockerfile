# platform-controller 镜像 · Go controller-runtime projection controller (K8s CR → DDB)
#
# build context = 本目录 (services/platform-controller/), module 自包含, 不依赖 platform-api。
#
#   docker build -t platform-controller:dev services/platform-controller/
#   (在本目录: docker build -t platform-controller:dev .)
#
# 运行时需要 aws CLI: entrypoint 用 `aws eks update-kubeconfig` 生成业务集群 kubeconfig,
# 且 kubeconfig 的 exec 插件调 `aws eks get-token` 拿 apiserver bearer token
# (client-go 自动在 15min 过期前刷新, 见 MANAGED_KUBECONFIG)。

# ---------- 构建阶段 ----------
FROM golang:1.26 AS build

WORKDIR /src

# GOPROXY: 默认 goproxy.cn (全球可达 CDN, 含 AWS EC2 各 region), 末尾 direct 兜底
# (私有/未镜像模块直连源站)。默认源 proxy.golang.org 在部分网络 (公司内网 DNS /
# 中国区) 不可达 → build 卡 i/o timeout, 故换全球稳的默认。
# 官方源可达的环境想用它: docker build --build-arg GOPROXY=https://proxy.golang.org,direct
# go.sum 校验每个模块哈希, 换代理不影响依赖内容一致性 (防篡改)。
ARG GOPROXY=https://goproxy.cn,direct
ENV GOPROXY=${GOPROXY}

# 先拉依赖 (go.mod/go.sum 不变时命中 layer cache, 不重复下载)。
COPY go.mod go.sum ./
RUN go mod download

# 再拷源码编译。CGO 关掉 → 纯静态二进制, 可跑在 distroless/scratch。
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build \
    -trimpath -ldflags="-s -w" \
    -o /out/controller ./cmd/controller

# ---------- aws CLI 阶段 (单独拉, 不污染最终镜像的构建工具) ----------
FROM public.ecr.aws/aws-cli/aws-cli:latest AS awscli

# ---------- 运行阶段 ----------
# debian-slim (非 distroless): 因为 entrypoint 需要 shell + aws CLI + kubectl 依赖的 ca-certs。
FROM debian:12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# aws CLI v2 (kubeconfig exec 拿 token 用)。
COPY --from=awscli /usr/local/aws-cli/ /usr/local/aws-cli/
RUN ln -s /usr/local/aws-cli/v2/current/bin/aws /usr/local/bin/aws

COPY --from=build /out/controller /usr/local/bin/controller
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 非 root 运行 (controller 只读 K8s + 写 DDB, 无需 root)。
# 用用户名 (非纯数字 uid) 且显式 HOME: 否则 HOME 默认 "/", aws CLI 和
# kubeconfig (entrypoint 写 $HOME/.kube/) 会写不进去。
RUN useradd -u 10001 -m -d /home/controller controller
ENV HOME=/home/controller
USER controller

ENTRYPOINT ["/entrypoint.sh"]
