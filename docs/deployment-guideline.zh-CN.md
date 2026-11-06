# HyperPod Team Portal · 部署指南

[English](deployment-guideline.md) | **简体中文**

在一个 AWS region 从零部署整套平台。

## 部署前环境要求 (执行机)

在跑部署脚本的那台机器上 (mac / Linux 均可, 推荐在本文档Step 0 之后，使用 [ec2-deployer-setup.zh-CN.md](ec2-deployer-setup.zh-CN.md) 在一台EC2上来进行部署) 先装好:

| 工具 | 版本要求 |
|---|---|
| **aws cli** | v2 |
| **kubectl** | ≥ 1.30 (与集群 1.35 差距别太大) |
| **helm** | v3 |
| **docker** | 在跑 (mac arm 需支持 `--platform linux/amd64`); 本机**不需要** node/pnpm, 前端在容器内构建 |
| **AWS CDK** | v2 (`aws-cdk-lib==2.150.0`, 全局 `cdk` ≥ 2.150) |
| **python3** | 3.11 |
| **git** | 任意 |


## EKS集群分工

- **业务集群** = HyperPod / FSx / 开发机所在 (控制台 custom setup 建)。
- **平台集群** = 前后端 / worker 所在 (CDK 建)。两集群同 VPC。

## 三个脚本分工

| 脚本 | 阶段 | 默认做什么 |
|---|---|---|
| `deploy/cluster-prereq.sh`  | 业务集群准备 (填完 cdk.json 后, CDK 前) | verify→ebs→ssm→pd→spaces→externaldns→logging→template→fsxadmin→lws |
| `deploy/deploy-platform.sh` | 平台部署 (CDK 起)     | init→build→apply (cdk 步骤要显式写) |
| `deploy/cognito-callback.sh`| 收尾                  | 回填 Cognito callback |

---

## 全流程总览

```
人工·控制台   建 VPC/子网/SG + custom setup 建 EKS+HyperPod + FSx(Lustre 2.15, 可多块)
                                  │
人工          填 infrastructure/cdk.json
                                  │
脚本①         cluster-prereq.sh   (业务集群 add-on/IAM/template/fsx-admin/directSSH; 自动读 cdk.json)
                                  │
脚本②         deploy-platform.sh  (cdk → init → build → apply)
                                  │
人工·收尾     cognito-callback.sh  +  cross-cluster-sg.sh 放行 8888/443  + 关联Identity Center用户组验证登录
```

---

## Step 0 · 控制台手动 (脚本不含)

1. **可选(HyperPod集群新创建VPC可跳过这步): VPC/子网/SG**: VPC CIDR 别与 EKS Service CIDR `172.20.0.0/16` 重叠 (如 `10.90.0.0/16`)。子网 public×2 + private-EKS×2 + private-HyperPod×1+。**HyperPod 节点子网与 FSx 同一个 AZ**。FSx SG 入站放通 **988 + 1018-1023**。
2. **必须(可VPC+HyperPod集群+FSx一起创建): 建 HyperPod集群**: Amazon SageMaker AI HyperPod clusters 控制台 → Orchestrated by Amazon EKS → Custom setup → Create HyperPod cluster → 输入Name → Networking选VPC等(推荐Create a new VPC,输入网段,选择3个AZ, 选择Create a new security group) → Orchestration 选 "Create a new EKS cluster" → Kubernetes version选1.35  →  Operators除了默认必选，再选上HyperPod patching和HyperPod training operator  → Instance Group 选择 Add group(可以先加一个CPU的instance group, 机型选择m5.4xlarge以上, 数量2以上) → Permissions选择Create a new IAM role → FSx file system保持默认选择，也可按需调整Throughput per unit of storage 和Storage capacity等(若同VPC已建好FSx文件系统,选择None即可) → 其他保持默认即可 → Submit** 。建出 EKS + HyperPod, 自动选择基础 add-on + IAM role + Pod Identity。 但**不含 spaces / ebs-csi** (后面脚本补装这两个add on)。
3. **可选 修改业务EKS集群为private**: 在Console进入EKS,找到Hyperpod集群创建出来的EKS集群, 修改集群为private, Networking → Manage → Endpoint access → Private → Save changes
4. **可选(HyperPod集群已创建可跳过这步) 建 FSx for Lustre**: FSx console → Persistent SSD, ≥1.2TiB, 选 EKS 同 VPC/ subnet 选择相同AZ，SG允许 EKS的SG访问 988 + 1018-1023 端口。**Lustre 版本必须选 2.15** (2.12 不支持 project quota, 目录配额会静默失效: `lfs setquota` 看着成功但 `lfs quota` 返回 `Operation not supported`; 控制台默认给 2.12, 需展开高级设置显式改)。**记下 File system ID (`fs-xxxx`)**。可建多块 (平台支持多 FSx), 每块都记下 id。
5. **必须: 优先级档 (cluster policy)**: 优先级档的权威源是 SageMaker HyperPod task governance 的 **cluster policy** (`ClusterSchedulerConfig`)，平台不再自建 Kueue WorkloadPriorityClass（`deploy/k8s/workload-priority-classes.yaml` 已废弃、cluster-init 不再 apply）。平台六类任务 (dev/train/inference/dynamo/llmd/rayjob) 默认都打 `common-priority` 档，而 HyperPod 集群自带的 cluster policy 里**没有 `common`**，需手动补建。CR 引用的 WPC 名 = policy 里的 class 名 + `-priority` 后缀（如 policy 填 `common` → 生成 WPC `common-priority`）。

   - **新安装**: SageMaker AI 控制台 → HyperPod Clusters → 选集群 → **Policies** 标签 → **Cluster policy** 编辑 → **Task prioritization 选 `Task ranking`** → 在 **Priority classes** 里 **Add**，Name 填 `common`，Weight 填 `80`（0-100，越大越优先）→ 保存。生效后 SageMaker 会在集群里自动建出托管的 `common-priority` WPC。

   - **更新安装 (旧版升级)**: 旧版本由 `deploy/k8s/workload-priority-classes.yaml` 在业务集群建了一批**自建的** WorkloadPriorityClass (`common-priority`/`high-priority`/`extremely-high-priority`/`low-priority`/`extremely-low-priority` 等)。升级时**必须先删除全部自建档**，否则 cluster policy 生成同名 WPC 时冲突（报 `already exists and is not managed by SageMaker`，policy 变 `UpdateFailed`）。自建档没有 `sagemaker.amazonaws.com/sagemaker-managed-queue` 这个 label，官方托管档才有，用负向 label selector 精确筛：

     ```bash
     # ① 先列出将删的自建 (非 SageMaker 托管) 档, 肉眼核对都是自建残留
     kubectl --context "$BUSINESS_CTX" get workloadpriorityclass \
       -l '!sagemaker.amazonaws.com/sagemaker-managed-queue'

     # ② 确认无误后删除 (只删非托管档, 官方托管档不受影响)
     kubectl --context "$BUSINESS_CTX" delete workloadpriorityclass \
       -l '!sagemaker.amazonaws.com/sagemaker-managed-queue'
     ```

     删完后，在**平台 UI「优先级档位」页**新建 `common` 档（Name 填裸名 `common`，权重 0-100）；或走上面「新安装」的控制台 cluster policy 方式。UI 建档实际调 SageMaker `CreateClusterSchedulerConfig`，由 task governance 接管生成托管 WPC。

   > ⚠️ 已在跑/排队的任务优先级是**创建时的数值快照**，删自建档不影响它们继续运行；但删档前确认没有会被重建 (重启/auto-resume) 的关键任务依赖这些档 (重建后会找不到档 → Kueue 回退 priority=0)。
   >
   > **权限**: 操作 cluster policy 需要 `sagemaker:{Describe,List}Cluster`、`sagemaker:ListClusterSchedulerConfigs`、`sagemaker:{Describe,Create,Update,Delete}ClusterSchedulerConfig`，以及 `eks:DescribeCluster` + `eks:AccessKubernetesApi`。UI 建档由 platform-api 后端角色发起，该角色须含上述 `*ClusterSchedulerConfig` 权限 (见 CDK 后端角色 policy)。

---

## Step 1 · 填 cdk.json (人工)

编辑 `infrastructure/cdk.json` 的 `context`:

| key | 填什么 |
|---|---|
| `projectName` | 项目前缀 (资源名前缀, 如 `hpd-plat`) |
| `account` / `region` | 账号 / region |
| `vpcId` / `privateSubnetIds` | 部署文档Step0 建的 VPC + 有NAT Gateway的私有子网 (≥2) |
| `platformClusterSuffix` | 平台 EKS 集群名后缀, 集群名 = `{projectName}-{platformClusterSuffix}` (默认 `deployplat`) |
| `platformK8sVersion` | 平台 EKS K8s 版本 (如 `1.35`) |
| `businessClusterName` / `hyperpodClusterName` | 业务集群 EKS 名 / HyperPod 名 |
| `hyperpodClusterLogGroupName` | HyperPod 集群容器日志的 CloudWatch log group 全名 `/aws/sagemaker/Clusters/<集群>/<id>`; 后端日志快路径用, 留空则走反查兜底 |
| `logArchiveMode` | 日志备份到 S3 的模式: `cost` = Firehose 原样落 gz, 省存储 (需 Glue ETL 转 Parquet 才好查); `query` = 解压 + 明文落地, Athena 直查, S3 体积大; 留空 = 不部署日志备份栈 |
| `platformFsxFilesystems` | 平台接入的 FSx 列表, 逗号分隔 `fs-id` (如 `fs-0aaa,fs-0bbb`)。fs-id 直接作 fsx-admin pod 里的挂载点子目录 `/fsx-mnt/<fs-id>` (天然路径安全); 前端配额/监控下拉的展示名走 AWS `Tags[Name]` (显示为 `名字 (fs-id)`)。**每块盘都必须是 Lustre 2.15** (见 Step0 §4)。留空则配额/监控页无盘可选。(兼容旧格式 `fs-id:别名`, 别名段会被忽略。) |
| `directSshDomain` | 开发机原生 SSH (directSSH) 用的**私有**域名, 如 `dev-ssh.hyperpod.internal` (内网域名, 自己取, 不用买)。填了 `cluster-prereq.sh` 才建 directSSH 全套 (Route53 私有 zone + external-dns role/addon + spaces addon 开 directSSH 关 SSM), 开发机拿到停/启不变的固定 DNS 名 + 22222 端口; 留空则退回 SSM 连接 |
| `ampWorkspaceId` | observability add-on 的 AMP workspace id, 可直接打开Amazon Prometheus console找到对应的workspace的Workspace ID |
| `idcIdentityStoreId` / `idcRegion` | 接 Identity Center填, StoreId见IdentityCenter Console Settings->Identity source -> 右侧Identity Store ID |
| `idcAssumeRoleArn` | **仅跨账号填**: IdC 在 org 管理账号、应用在另一个账号时, 填管理账号一个只读角色 ARN (后端先 AssumeRole 再查 IdC)。同账号留空。建角色步骤见 [`identity-center-cognito-configuration.zh-CN.md`](identity-center-cognito-configuration.zh-CN.md) §4。注意此时 `idcIdentityStoreId`/`idcRegion` 仍要填管理账号那个 store 的值 |
| `platformS3Buckets` | 挂载用 S3 桶, 格式 `bucket[:region[:友好名]]`, 逗号分隔多个 |
| `albDomainName` | 平台访问域名 (有域名再填) |
| `albCertificateArn` | 平台 ALB 的 HTTPS 证书 ARN (ACM, **须与 ALB 同 region**), 形如 `arn:aws:acm:<region>:<account>:certificate/xxxx`。**留空 = 仅 HTTP:80**; 填了 = 开 HTTPS:443 (80 自动跳 443)。内网域名的私有证书创建见 [`internal-domain-deployment.zh-CN.md`](internal-domain-deployment.zh-CN.md) §2 建 Private CA → §3 用该 CA 签证书入 ACM (这里填 §3 产出的 ACM 证书 ARN, 不是 §2 的 CA ARN) |
| `platformNamespace` | 平台前后端所在 K8s namespace (默认 `platform-system`) |
| `platformEndpointPublicAccess` | 平台集群 API endpoint 是否开公网。`true` = local kubectl 可直连 (联调期); `false`/缺省 = private-only (生产, 运维走 VPC 内 EC2/VPN)。切 private 改 false 重 cdk deploy |
| `clusterWorkspaceAdminGroup` | 默认 `cluster-workspace-admin` 即可; 仅当业务集群 spaces operator 的 `CLUSTER_ADMIN_GROUP` 非默认时才改 (须一致) |
| `bootstrapAdmins` | 初始超管 username, 多个逗号分隔 |

填完后装 CDK Python 依赖 + bootstrap (新账号首次):

```bash
cd infrastructure && python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cdk bootstrap && cd ..   # 新账号及region首次, 已 bootstrap 可跳
```

---

## Step 2 · 业务集群准备 (脚本①)

参数自动从 cdk.json 读 (region/account/businessClusterName/platformFsxFilesystems/directSshDomain), 直接跑:
 
```bash
chmod +x deploy/*.sh
./deploy/cluster-prereq.sh
```

脚本依次做: `verify` 验证 → `ebs` 装 EBS CSI + role → `ssm` 建 SSM role → `pd` 开 Prefix Delegation + 装 maxpods-patcher (抬 maxPods, **必须在 spaces 前**) → `spaces` 装 spaces add-on → `externaldns` 建 directSSH 的 Route53 zone + role + external-dns add-on → `logging` 开容器日志 → `template` 开 allowCustomImages → `fsxadmin` 起 fsx-admin pod (挂 `platformFsxFilesystems` 里的每块盘) → `lws` 装 LeaderWorkerSet (llm-d 多机推理)。

> ⚠️ `pd` 在 `spaces` 之前是必须的: HyperPod 节点默认单 ENI 只 ~29 pod, 不先抬 maxPods, spaces 等 add-on 的 pod 调度不出来 → add-on `DEGRADED`。

> `spaces` / `externaldns` 都看 cdk.json `directSshDomain`: 填了则 spaces add-on 开 `directSSH` (端口 22222) 并关掉 remoteAccess(SSM), 同时 `externaldns` 建私有 zone + IAM role + external-dns add-on, 把 spaces 自动创建的 SSH Service 同步成固定 DNS 名; 留空则 spaces 走 remoteAccess(SSM), `externaldns` 自动跳过。zone 和 role 都由脚本自建 (**不在 CDK**): 脚本跑在 `cdk deploy` 之前, add-on 依赖 role、role policy 依赖 zone ARN, 三者必须先于 CDK。开发机 SSH 还需 `deploy/cross-cluster-sg.sh` 放通节点 SG 的 22222 (见 Step4 §2)。

> `fsxadmin` 按 cdk.json `platformFsxFilesystems` 起**一个** fsx-admin pod 挂**多块盘**, 每块一对 PV/PVC (`fsx-admin-pv-<fs-id>`), 挂载点 `/fsx-mnt/<fs-id>`; DNS 名和 MountName 脚本自动 describe, 不用手填。改了盘列表重跑 `./deploy/cluster-prereq.sh fsxadmin` 即可 (Deployment 是删后重建, 不会残留已移除盘的旧挂载)。

> spaces 装完到 template seed 出来有 1-2 分钟延迟。若 `template` 步骤报"取不到 workspacetemplate", 等一会儿单独重跑: `./deploy/cluster-prereq.sh template`。

> `logging` 步骤把 observability **add-on 的 configurationValues** 里 `metricsProvider.logging.enabled` 设为 `true`（`aws eks update-addon`，读现有 config 合并后写回，不动 AMP/Grafana/metrics 等其他配置），operator 会自动拉起 `fluent-bit` DaemonSet，把容器日志（训练/开发机）推到 CloudWatch log group `/aws/sagemaker/Clusters/<集群>/<id>`。**不开这步训练日志上不了 CloudWatch**。权限走 add-on 自带 SA（已含 `logs:*` on `/aws/sagemaker/Clusters/*`），无需额外建 IAM。约 1 分钟后用 `kubectl get ds -n hyperpod-observability | grep fluent-bit` 验证。

可单跑某几步: `./deploy/cluster-prereq.sh pd` (开 PD + maxpods) / `./deploy/cluster-prereq.sh ebs ssm spaces` / `./deploy/cluster-prereq.sh externaldns` / `./deploy/cluster-prereq.sh fsxadmin` / `./deploy/cluster-prereq.sh logging` / `./deploy/cluster-prereq.sh verify`。

---

## Step 3 · 平台部署 (脚本②)

```bash
# 全自动 (含 cdk, ⚠️ 自动批准 IAM 变更)
./deploy/deploy-platform.sh cdk init build apply

# 或: 先手动 cdk deploy 看 diff, 再跑默认三步
cd infrastructure && cdk deploy <projectName>-platform-stack && cd ..
./deploy/deploy-platform.sh        # = init build apply

# 指定镜像 tag
TAG=v2 ./deploy/deploy-platform.sh

# 只重 apply (改了 manifest)
./deploy/deploy-platform.sh apply
```

各步: `cdk` 建平台集群+资源 → `init` kubeconfig+access entry+ALB+业务集群 RBAC(platform-api-manager) → `build` push 3 镜像 → `apply` 渲染 manifest 部署。`init/build/apply` 自动从 cdk.json + CDK Output 读参, 不用手抄 ARN。(优先级档不再由 init 建, 见 Step 0 第 5 条)

---

## Step 4 · 收尾 (脚本&人工)

```bash
# 1. 回填 Cognito callback (默认 localhost:8080, SSM 隧道联调用)
./deploy/cognito-callback.sh 
#  生产域名: CALLBACK_URL=https://platform.example.com/auth/callback ./deploy/cognito-callback.sh

# 2. 跨集群安全组放行 (不放则监控/开发机不可用 → 后端连不上开发机 8888 → 浏览器 504)
#    脚本自动查 DST_SG(HyperPod 集群 SG=开发机 pod SG) + SRC_SG(平台节点 SG), 放行 8888/443
#    cdk.json 填了 directSshDomain 时, 额外放行 22222 给 VPC 全部 CIDR (含 secondary CIDR),
#    否则用户从 VPC 内机器 ssh 开发机会 TCP 超时
./deploy/cross-cluster-sg.sh           # 自动查 + 放行
./deploy/cross-cluster-sg.sh verify    # 只查 SG 打印, 不改
```

- **注意 · 推理服务 (单机 / 多机) 需手工放行 ALB → pod**：在 EKS 的 **Additional security groups** 上加入站规则，源填 ALB 的**共享后端 SG** `k8s-traffic-<集群>-<hash>`，端口 30000（多机推理 gateway）。
  原因：HyperPod + Prefix Delegation 下 LBC 解析不到 pod ENI，这条规则它自动加不上。不加则 ALB 返回 504（target 已注册但健康检查超时）。

> 可选: 验证连通 (后续在平台上验证也行放行后)(起一台开发机, 从后端 pod 测, 毫秒级=通 / 10s 超时=没放行):
> ```bash
> kubectl --context <platform-ctx> -n platform-system exec deploy/platform-api -- \
>   curl -s -m 10 -o /dev/null -w "%{http_code} %{time_total}s\n" http://<开发机 pod IP>:8888/
> ```

3. (可选) 给Hyperpod集群加一个GPU instance group 。复用一个已有 instance group 的 LifeCycleConfig/ExecutionRole/SG 。**需先在脚本顶部填**: `NEW_IG_NAME` / `INSTANCE_TYPE` / `INSTANCE_COUNT` / `SUBNET_ID` / `SOURCE_IG_NAME`(继承自哪个组)。

   ```bash
   ./deploy/create_new_instance_group.sh
   ```

4. 配置identity center + cognito, 见文档 [identity-center-cognito-configuration.zh-CN.md](identity-center-cognito-configuration.zh-CN.md)

5. 配置internal 域名到平台, 见文档 [internal-domain-deployment.zh-CN.md](internal-domain-deployment.zh-CN.md)

---

## 常见问题

| 现象 | 处理 |
|---|---|
| 打开开发机 `504 Gateway Timeout` (CloudFront) | 后端连不上开发机 pod 的 8888 → 跨集群 SG 没放行对。按 Step4 §2 放行 **DST_SG=HyperPod 节点 SG / SRC_SG=平台节点 SG**。后端日志会有 `dev_instance.proxy.upstream_err`。注意源 SG 别填成 ALB/k8s-traffic SG (ENABLE_POD_ENI=false 时 pod 走节点出网) |
| Code Editor `WebSocket 1006` / 空白 | code-server 暴露 pod 内网 IP, SSM 隧道下难根治, 联调用 VSCode Remote-SSH |
| 新 pod 起不来 `too many pods` / add-on `DEGRADED` | 节点 maxPods 没抬高 (默认 ~29)。跑 `./deploy/cluster-prereq.sh pd` 开 PD + 装 maxpods-patcher (正常默认流程已含, 在 spaces 前) |
