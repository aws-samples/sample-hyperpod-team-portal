#!/usr/bin/env bash
#
# EC2 部署机软件安装 (Amazon Linux 2023, x86_64)。
# 装齐部署平台所需工具: aws cli / docker / kubectl / helm / python3.11 / node+cdk / git
# + Claude Code (Anthropic CLI, 走 Bedrock)。
# 只装软件, 不碰 IAM (role 在 docs/ec2-deployer-setup.md §1 建 EC2 时已配好关联;
# Claude Code 走 Bedrock 需 role 有 bedrock:InvokeModel* 权限, 见 ec2-deployer-policy.json)。
#
# 用法 (在 EC2 上, 已 unzip 代码并 cd 进仓库):
#   ./deploy/ec2-bootstrap.sh            # 全装
#   ./deploy/ec2-bootstrap.sh verify     # 只验证已装版本, 不安装
#
# 装完需重新登录 (docker 组生效) 或 newgrp docker。
set -euo pipefail

KUBECTL_VERSION="${KUBECTL_VERSION:-v1.31.0}"   # 配 EKS 1.35, 客户端差一两个小版本无妨

log() { echo -e "\n>>> $*"; }

verify() {
  log "版本核对"
  aws --version 2>&1 | head -1            || echo "❌ aws cli 缺失"
  docker --version 2>&1                   || echo "❌ docker 缺失"
  kubectl version --client 2>&1 | head -1 || echo "❌ kubectl 缺失"
  helm version 2>&1 | head -1             || echo "❌ helm 缺失"
  cdk --version 2>&1                      || echo "❌ cdk 缺失"
  { python3.11 --version || python3 --version; } 2>&1 || echo "❌ python3 缺失"
  git --version 2>&1                      || echo "❌ git 缺失"
  command claude --version 2>&1 | head -1 || echo "❌ claude-code 缺失"
  echo
  docker info >/dev/null 2>&1 && echo "✓ docker daemon 在跑" \
    || echo "⚠️ docker daemon 未跑或当前用户无权限 (重新登录 / sudo systemctl start docker / newgrp docker)"
  id -nG | grep -qw docker && echo "✓ 当前用户在 docker 组" \
    || echo "⚠️ 当前用户不在 docker 组 — 重新登录或 newgrp docker"
}

if [ "${1:-}" = "verify" ]; then verify; exit 0; fi

# ---- 架构提醒 ----
ARCH="$(uname -m)"
if [ "$ARCH" != "x86_64" ]; then
  echo "⚠️ 当前架构 $ARCH 非 x86_64。build-push 用 --platform linux/amd64,"
  echo "   非 x86 机器需 binfmt 模拟构建会很慢; 建议换 x86_64 EC2。继续? (Ctrl-C 中止)"
  sleep 5
fi

log "[1/7] 系统更新"
sudo dnf update -y -q

log "[2/7] aws cli v2 (官方 installer 装/升到最新)"
# 始终用官方 installer: dnf 的 awscli 包版本滞后 (常落后最新一大截), 且 --update 幂等,
# 已是最新也无害。不走 dnf, 避免装到旧版又被"已装则跳过"卡住升不上去。
sudo dnf install -y -q unzip >/dev/null 2>&1 || true   # installer 解压需要 unzip
rm -rf /tmp/aws /tmp/awscliv2.zip
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
(cd /tmp && unzip -oq awscliv2.zip && sudo ./aws/install --update --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli)
hash -r   # 刷新 bash 命令缓存, 否则当前 shell 仍指向旧 aws 路径
aws --version

log "[3/7] docker"
sudo dnf install -y -q docker
sudo systemctl enable --now docker
sudo usermod -aG docker "$(whoami)" || true
echo "   (docker 组需重新登录生效; 本次会话可 'newgrp docker')"

log "[4/7] git + python3.11"
sudo dnf install -y -q git python3.11 python3.11-pip

log "[5/7] Node.js + aws-cdk"
sudo dnf install -y -q nodejs npm
sudo npm install -g aws-cdk --silent
cdk --version

log "[6/7] kubectl $KUBECTL_VERSION"
curl -fsSLO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
sudo install -m 0755 kubectl /usr/local/bin/kubectl
rm -f kubectl
kubectl version --client | head -1

log "[7/8] helm v3"
if ! helm version >/dev/null 2>&1; then
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi
helm version | head -1

log "[8/8] Claude Code (Anthropic CLI) + Bedrock 配置"
# 装 CLI (node 上一步已装)。走 Bedrock: 凭证用 EC2 role (已挂 bedrock:InvokeModel*), 无需 API key。
# 用 profile.d 里的 claude shell 函数注入配置 (不全局 export, 零污染)。
# 模型用 global.* 全球跨区推理 profile: 不绑定区域, 走本机所在区的 Bedrock 端点即可,
# 不用写死 AWS_REGION (SDK 默认取本机 EC2 元数据的 region)。
sudo npm install -g @anthropic-ai/claude-code --silent
sudo tee /etc/profile.d/claude-code.sh >/dev/null <<'CLAUDE_ENV'
# Claude Code 走 Amazon Bedrock (凭证用 EC2 instance role)。
# 函数包装而非全局 export: 只在跑 claude 时注入, 不污染其它命令的环境。
# global.* = 全球跨区推理 profile, 不锁 region; 不设 AWS_REGION → 用本机所在区端点。
claude() {
  CLAUDE_CODE_USE_BEDROCK=1 \
  ANTHROPIC_MODEL='global.anthropic.claude-opus-4-8' \
  command claude "$@"
}
CLAUDE_ENV
command claude --version 2>&1 | head -1 || echo "  (claude 已装, 重新登录后 'claude' 函数生效)"
echo "   ✓ Claude Code 走 Bedrock, 模型 global.anthropic.claude-opus-4-8 (全球 profile, 不锁 region)。"
echo "     claude 函数已写 /etc/profile.d/claude-code.sh, 重新登录生效; 只影响 claude, 不动 AWS_REGION。"
echo "     EC2 role 需有 bedrock:InvokeModel* 权限 (见 ec2-deployer-policy.json), 且 Bedrock 已开 Opus 4.8 model access。"

verify

cat <<'NEXT'

============================================================
软件安装完成。接下来 (见 docs/ec2-deployer-setup.md):
  1. 重新登录 (或 newgrp docker) 让 docker 组生效
  2. §4 业务集群 access entry (把 EC2 role 加进业务集群, kubectl 才能连)
  3. §5 cd infrastructure 建 venv 装依赖 → cdk bootstrap → ./deploy/deploy-platform.sh cdk init build apply
============================================================
NEXT
