# platform-controller 部署指南

[English](controller-deployment.md) | **简体中文**

Go controller-runtime projection controller: 跨集群 watch 业务集群的三种 CR
(训练 HyperPodPyTorchJob / 推理 InferenceEndpointConfig / 开发机 Workspace) +
Kueue Workload + Pod,派生状态单向投影到 DynamoDB。**替代原 Python platform-worker。**

## 架构:跨双集群

```
┌─ 平台集群 (集群 X) ────────────┐        ┌─ 业务集群 (集群 Y, hyperpod) ─┐
│  platform-controller Pod       │        │                                │
│   - leader election lease ─────┼── 本集群 in-cluster SA               │
│   - watch CR/Workload/Pod ─────┼───────▶│  只读 (access entry + RBAC)   │
│   - 写 DynamoDB                 │        │                                │
└────────────────────────────────┘        └────────────────────────────────┘
```

- **业务集群(watch 目标)**:`BUSINESS_EKS_CLUSTER_NAME` → entrypoint `aws eks update-kubeconfig`
  生成 kubeconfig(`BUSINESS_KUBECONFIG` 指向它),exec 段 `aws eks get-token` 拿 token
  (client-go 自动刷新,不撞 15min 401)。
- **平台集群(controller 所在)**:leader election 的 lease 放这里(不在业务集群放任何东西),
  用 Pod 自己的 ServiceAccount(in-cluster,`PLATFORM_KUBECONFIG` 留空)。

> **Pod 部署只需传业务集群名**(`BUSINESS_EKS_CLUSTER_NAME`):`BUSINESS_KUBECONFIG` 由 entrypoint
> 自动生成,`PLATFORM_KUBECONFIG` 留空走 in-cluster。两个 `*_KUBECONFIG` 只在本地开发时才手动指定路径。

## 前置:IAM 身份权限

controller 的运行身份(Pod Identity 或 IRSA)需要:

| 权限 | 用途 |
|---|---|
| `eks:DescribeCluster`(业务集群) | entrypoint `update-kubeconfig` 读 endpoint + CA |
| 业务集群 **access entry** | apiserver 认这个 IAM 身份,映射到 RBAC group |
| DynamoDB `GetItem`/`UpdateItem`(目标表) | 投影写 DDB |

## 部署步骤

### 1. 构建 + 推镜像

```bash
cd services/platform-controller
docker build -t <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/<PROJECT>-platform-controller:<TAG> .
aws ecr get-login-password --region <REGION> | docker login --username AWS --password-stdin <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com
docker push <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/<PROJECT>-platform-controller:<TAG>
```

### 2. 业务集群授权(RBAC + access entry)

```bash
# access entry: 把 IAM role 映射成 K8s group "platform-controller"
aws eks create-access-entry --cluster-name <BUSINESS_EKS_CLUSTER> \
  --principal-arn arn:aws:iam::<ACCOUNT>:role/<PROJECT>-platform-controller \
  --kubernetes-groups platform-controller --type STANDARD

# 只读 RBAC (CR/Workload/Pod 的 get/list/watch)
kubectl --context <业务集群> apply -f deploy/business-cluster-rbac.yaml
```

### 3. 平台集群部署

编辑 `deploy/deployment.yaml` 替换占位符(`<ACCOUNT>` `<REGION>` `<PROJECT>` `<TAG>`
`<DDB_TABLE>` `<BUSINESS_EKS_CLUSTER>`),然后:

```bash
kubectl --context <平台集群> apply -f deploy/deployment.yaml
```

这一步创建 ServiceAccount + leader election 的 Role/RoleBinding(本集群 leases 权限)+ Deployment。

### 4. 首次上线:先 DRY_RUN 验证,再真写

⚠️ **迁移唯一写者约束**:同一张 DDB 表不能同时被 Python worker 和 Go controller 真写。

```
1. 确认 Python platform-worker 已停 (scale 到 0 或删 Deployment)
2. deployment.yaml 里 DRY_RUN=true 先部署 → 看日志确认派生正确 (不写库)
   kubectl -n platform-system logs -f deploy/platform-controller
   # 日志形如: [DRY_RUN] UpsertStatus key=.../inference#... ks=Admitted phase=...
3. 验证无误 → 改 DRY_RUN=false, kubectl apply → Go 成为唯一写者
```

## 配置(环境变量)

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `AWS_REGION` | | us-west-2 | |
| `DDB_TABLE` | ✅ | | ResourceIndex 表**全名**(非前缀) |
| `BUSINESS_EKS_CLUSTER_NAME` | ✅ | | 业务集群名(entrypoint 生成 kubeconfig) |
| `DRY_RUN` | | false | true=只 log 不写库(首次验证) |
| `ENABLE_LEADER_ELECTION` | | true | 多副本热备时用 |
| `LEADER_ELECTION_NAMESPACE` | | platform-system | lease 放哪个 ns(本集群) |
| `PLATFORM_KUBECONFIG` | | (空=in-cluster) | 平台集群 kubeconfig;Pod 内留空 |
| `BUSINESS_KUBECONFIG` | | (entrypoint 设) | 业务集群 kubeconfig 路径;Pod 内 entrypoint 自动生成 |

## 健康检查

- `:8081/healthz`(liveness)、`:8081/readyz`(readiness)
- `:8080/metrics`(Prometheus)

## 资源占用(实测参考)

| | Python worker | Go controller |
|---|---|---|
| requests | cpu 200m / mem 512Mi | **cpu 50m / mem 64Mi** |
| limits | cpu 1 / mem 1Gi | **cpu 500m / mem 256Mi** |
| 实测 RSS | — | ~35Mi(含 cache) |
| 镜像 | ~260MB(python+venv) | ~与 debian-slim+二进制 相关,二进制本身 46MB |

## 运维要点

- **单实例即可**;需要热备可加副本,leader election 保证只 1 个干活。
- **重启无害**:level-based reconcile,重启后从 cache 读齐重算;删除索引(内存)重启会丢,
  靠 10h resync 兜底(删除本由前端 DELETE 接口收口)。
- **回滚**:改回 Python worker 时,先停 Go controller(避免双写)再起 worker。
