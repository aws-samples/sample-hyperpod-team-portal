# EC2 Deployment Host Setup

**English** | [简体中文](ec2-deployer-setup.zh-CN.md)

Run the entire deployment from an EC2 instance inside the VPC where the HyperPod EKS cluster lives. Because the EC2 instance is in the same VPC as the clusters, it can reach the backend pods directly, which saves you from dealing with cross-cluster networking.

- For the account, Region, VPC, and so on, see `infrastructure/cdk.json`
- First create the instance + role, then sign in and pull the code from the GitHub repo (for a private repo, use a deploy key for password-less access; see §2)

---

## 1. Create the EC2 instance + IAM role (console, as Admin)

1. **Create the IAM role** (IAM console → Roles → Create role → for trusted entity type, choose **EC2**; name it as you like, recommended `hyperpod-ec2-deployer`) and attach 3 policies:
   - `ec2-deployer` — an inline policy; paste the contents of `docs/ec2-deployer-policy.json` (includes the CFN/EKS/ECR/IAM and other permissions needed for deployment; it also includes **the `route53:*` private hosted zone group** — used to create the private hosted zone for dev instance directSSH (the `cluster-prereq.sh externaldns` step) and the private hosted zone/A records for the internal domain name; and **`bedrock:InvokeModel*`** — so that Claude Code on the EC2 instance can use Amazon Bedrock, see §3)
   - `AmazonS3ReadOnlyAccess` (AWS managed) — for reading from S3 during deployment (image build sources, S3 mounts, and so on)
   - `AmazonSSMManagedInstanceCore` (AWS managed) — for signing in through SSM
2. **Create the EC2 instance**: AL2023 / x86_64 / private subnet (in the same VPC as the clusters) / EBS ≥ 50 GB.
   When creating the instance, under "Advanced details → IAM instance profile", choose the role above.
3. **Attach the role to the EC2 instance** (if you did not choose it when creating the instance): EC2 console → select the instance → **Actions → Security → Modify IAM role**
   → choose the role above → Update IAM role.
   > When you choose a role for EC2, what you actually choose is the **instance profile** with the same name. Creating a role (with EC2 trust) in the console automatically creates an instance profile
   > with the same name, so you can choose it directly (only when you create the role with the CLI do you need to run create-instance-profile + add-role manually).

## 2. Pull the code (from the GitHub repo)

You can connect to the EC2 instance through SSM Session Manager or SSH. After signing in through SSM, pull the code from the GitHub repo:

```bash
# Install git first if it is not installed (AL2023)
sudo dnf install -y git

# Pull from the GitHub repo (replace with the actual repo URL; for a private repo, see "Pulling a private repo" below)
git clone <github-repo-url>
cd hyperPod-controller
```

> **Pulling a private repo**: Configure a read-only deploy key on the EC2 instance for the repo (no account password needed):
> 1. Generate a key on the EC2 instance: `ssh-keygen -t ed25519 -f ~/.ssh/gh_deploy -N ""`, then copy `~/.ssh/gh_deploy.pub`
> 2. GitHub → your avatar in the upper-right corner → Settings → SSH and GPG keys → New SSH key → paste the string above → save
> 3. Configure SSH on the EC2 instance: add a `Host github.com` section to `~/.ssh/config` that points to `~/.ssh/gh_deploy`, then clone with the SSH URL `git clone git@github.com:<owner>/<repo>.git`

## 3. Install dependencies

```bash
./deploy/ec2-bootstrap.sh          # installs aws/docker/kubectl/helm/python3.11/node+cdk/git + Claude Code
# Sign in again (or run newgrp docker) so the docker group takes effect

export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION=ap-south-2
export ANTHROPIC_MODEL='global.anthropic.claude-opus-4-8'

```

> **Claude Code (through Bedrock)**: The script installs the Anthropic Claude Code CLI and defines a `claude` function in `/etc/profile.d/claude-code.sh`
> (it uses Amazon Bedrock with the EC2 role's `bedrock:InvokeModel*` permission, so no API key is needed).
> After signing in again, just run `claude`. Prerequisite: model access for the corresponding model must be enabled in Bedrock in the EC2 instance's Region.
> This Bedrock permission is already included in the `ec2-deployer` inline policy from §1.

## 4. Business cluster access entry for the EC2 role (required for kubectl to connect to the business cluster)

```bash
ROLE_ARN=arn:aws:iam::<account>:role/<role-name-created-above>   # recommended default: hyperpod-ec2-deployer
aws eks create-access-entry --cluster-name <business-cluster> --region <region> --principal-arn $ROLE_ARN
aws eks associate-access-policy --cluster-name <business-cluster> --region <region> --principal-arn $ROLE_ARN \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy --access-scope type=cluster
```

## 5. Run the deployment

Once the software is installed and the code is in place, return to the main deployment guide and follow it in order, starting from **Step 1 (Fill in cdk.json)**:
[`deployment-guideline.md`](deployment-guideline.md) — fill in cdk.json + install CDK dependencies → business cluster preparation → platform deployment → wrap-up.

