# EC2 部署机 setup

[English](ec2-deployer-setup.md) | **简体中文**

在 Hyperpod EKS集群 所在 VPC 内的一台 EC2 上跑整套部署。EC2 与集群同 VPC, 后端 pod 互通, 省跨集群网络折腾。

- 账号/region/VPC 等看 `infrastructure/cdk.json`
- 先建机器+role, 登录后从 GitHub repo 拉代码 (私有仓用 deploy key 免密, 见 §2)

---

## 1. 建 EC2 + IAM role (控制台, 用 Admin 身份)

1. **建 IAM role** (IAM 控制台 → 角色 → 创建角色 → 信任实体类型选 **EC2**, 名字自定, 建议 `hyperpod-ec2-deployer`), 挂 3 个 policy:
   - `ec2-deployer` — inline policy, 内容粘 `docs/ec2-deployer-policy.json` (含部署所需 CFN/EKS/ECR/IAM 等权限; 另含 **`route53:*` 私有区那组** —— 建开发机 directSSH 的私有 hosted zone (`cluster-prereq.sh externaldns` 步) 和内网域名的私有区/A 记录用; 以及 **`bedrock:InvokeModel*`** —— 供 EC2 上的 Claude Code 走 Amazon Bedrock, 见 §3)
   - `AmazonS3ReadOnlyAccess` (AWS 托管) — 部署过程读 S3 (镜像构建 source / S3 挂载等) 用
   - `AmazonSSMManagedInstanceCore` (AWS 托管) — SSM 登录用
2. **建 EC2**: AL2023 / x86_64 / 私有子网(与集群同 VPC) / EBS ≥ 50 GB。
   建实例时"高级详细信息 → IAM 实例配置文件"选上面这个 role。
3. **关联 role 到 EC2** (若建实例时没选): EC2 控制台 → 选中实例 → **操作 → 安全 → 修改 IAM 角色**
   → 选上面的 role → 更新。
   > EC2 选 role 时实际选的是同名 **instance profile**; 控制台建 role(EC2 信任)会自动建同名
   > instance profile, 直接选即可 (CLI 建 role 才需手动 create-instance-profile + add-role)。

## 2. 拉取代码 (从 GitHub repo)

可通过 SSM Session Manager 或 SSH 连接到 EC2。SSM 登录后, 从 GitHub repo 拉取代码:

```bash
# git 未装的话先装 (AL2023)
sudo dnf install -y git

# 从 GitHub repo 拉取 (换成实际 repo 地址; 私有仓见下方"私有仓拉取")
git clone <github-repo-url>
cd hyperPod-controller
```

> **私有仓拉取**: 给该 repo 配一个 EC2 上的只读 deploy key (免账号密码):
> 1. EC2 上生成 key: `ssh-keygen -t ed25519 -f ~/.ssh/gh_deploy -N ""`, 复制 `~/.ssh/gh_deploy.pub`
> 2. GitHub → 右上头像 → Settings → SSH and GPG keys → New SSH key → 粘贴上面那串 → 保存
> 3. EC2 配 SSH: 在 `~/.ssh/config` 加 `Host github.com` 段指向 `~/.ssh/gh_deploy`, 然后用 SSH 地址 `git clone git@github.com:<owner>/<repo>.git`

## 3. 装依赖

```bash
./deploy/ec2-bootstrap.sh          # 装 aws/docker/kubectl/helm/python3.11/node+cdk/git + Claude Code
# 重新登录 (或 newgrp docker) 让 docker 组生效

export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION=ap-south-2
export ANTHROPIC_MODEL='global.anthropic.claude-opus-4-8'

```

> **Claude Code (走 Bedrock)**: 脚本装了 Anthropic Claude Code CLI, 并在 `/etc/profile.d/claude-code.sh`
> 定义了 `claude` 函数 (走 Amazon Bedrock, 用 EC2 role 的 `bedrock:InvokeModel*` 权限, 无需 API key)。
> 重新登录后直接 `claude` 即可。前提: EC2 所在 region 的 Bedrock 已开对应模型的 model access。
> 该 Bedrock 权限已含在 §1 的 `ec2-deployer` inline policy 里。

## 4. EC2 role 业务集群 access entry (kubectl 连业务集群必需)

```bash
ROLE_ARN=arn:aws:iam::<account>:role/<上面建的 role 名>   # 默认建议 hyperpod-ec2-deployer
aws eks create-access-entry --cluster-name <业务集群> --region <region> --principal-arn $ROLE_ARN
aws eks associate-access-policy --cluster-name <业务集群> --region <region> --principal-arn $ROLE_ARN \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy --access-scope type=cluster
```

## 5. 跑部署

软件装好、代码就位后, 回主部署文档从 **Step 1 (填 cdk.json)** 开始按顺序执行:
[`deployment-guideline.zh-CN.md`](deployment-guideline.zh-CN.md) — 填 cdk.json + 装 CDK 依赖 → 业务集群准备 → 平台部署 → 收尾。

