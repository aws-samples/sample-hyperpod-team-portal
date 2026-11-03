# platform-worker

K8s informer worker · watch HyperPodPyTorchJob CR → 写 DDB ResourceIndex.phase.

替代旧的 request-driven sync (打开页面才同步)。事件驱动实时落库, 且捕获
绕过 UI 直接 kubectl apply 提交的任务。DDB 原子条件写 (resourceVersion) 保证
任意副本数安全 (replica=1 省资源 / replica=2 高可用都行)。

## 配置 (独立 .env)

worker 在 ECS 上是**独立 service**, 跟 platform-api 各自注入环境变量, 所以本地也用
**独立 .env** (不软链 / 不复用 api 的), 跟生产形态一致。

`get_settings()` 相对 CWD 读 `.env`, 启动时 CWD = `services/platform-worker/`, 所以
worker 自己目录要有 `.env`。

```
cd services/platform-worker
cp .env.example .env        # 然后填真实值 (AWS / DDB / EKS)
```

worker 只需要这些配置 (不需要 api 的 Cognito / IdC / FSx / S3 / ALB):
- `AWS_REGION` / `AWS_PROFILE`
- `DDB_TABLE_PREFIX` / `DDB_ENDPOINT_URL` (留空走真 AWS)
- `EKS_CLUSTER_NAME` / `HYPERPOD_CLUSTER_NAME` / `KUBE_CONTEXT` (空=当前 context)

## 本地起 (复用 platform-api venv, 但用 worker 自己的 .env)

```
# 复用 platform-api venv (已含 platform-api 包 + kubernetes-asyncio + aioboto3)
cd services/platform-worker
PYTHONPATH=.:../platform-api ../platform-api/.venv/bin/python -m worker.main
```

## 本地双进程

- 终端1 (API): `cd services/platform-api && .venv/bin/uvicorn app.main:app --port 8800 --reload`
- 终端2 (worker): 见上

## 验证

1. 启动 → 日志 `cold_start.done n=N` (N = 集群现有训练 CR 数)
2. UI 建训练任务 → 日志 `reconcile job_id=... phase=Pending wrote=True` → DDB 出现该行
3. `kubectl apply` 绕过 UI 的 job (无 platform label) → 日志 reconcile (从 namespace
   反推 ws) → DDB 补行 → 列表能看到
4. 任务跑完 (Pod 退出) → 日志 phase=Succeeded (不依赖开页面)
5. worker 重启 → 重新 LIST → 已终态任务 wrote=False (rv 条件挡掉, 不回退)

## 健壮性机制 (阶段 0 加固)

- **毒丸 CR 隔离**: 单条 CR reconcile 失败记日志+计数, 跳过不炸全程 (故障域 A)。
- **假死克星**: 客户端 `_request_timeout=5min` 强制 watch 周期返回, rv 续传 (不 LIST) 重连; 打破 NAT/LB 静默回收导致的半开连接假死 (故障域 B)。LIST 仅在首启 + 410(罕见)。
- **看门狗**: 心跳超 15min 无进展 → `sys.exit(1)`, 编排器重启 (进程退出契约, 编排中立)。
- **/healthz**: 查心跳返回 200/503, 编排器探活 (与看门狗双保险)。port 8080。
- **异常分类**: 瞬时错误(网络/5xx)退避重试; 致命(bug/401/403)fail-fast 退出。
- 部署中立: 自愈靠进程退出 + 编排器重启, 探活靠 HTTP, ECS/EKS 通用。

时间参数: 周期超时=300s / 看门狗阈值=900s / 看门狗检查=30s / health port=8080。

### 可观测性 (日志)

- 默认 `LOG_LEVEL=INFO`: 只打里程碑 (cold_start / reconcile 写入 / 410 / 看门狗触发 / 错误)。稳态运行安静。
- `LOG_LEVEL=DEBUG`: 额外打全量细节, 用于排查:
  - `watch.cycle start/end rv=... timeout=...`: 每个 watch 周期起止 (续传可见, 标注 no LIST)
  - `watch.event type=... name=... rv=...`: 每个收到的事件
  - `watchdog.check age=... threshold=... ok`: 看门狗每次检查 (确认心跳在刷新)
  - `health.probe code=... age=...`: 每次 /healthz 探活
- 启动示例: `LOG_LEVEL=DEBUG python -m worker.main`
- 周期超时用 `asyncio.timeout()` (非 kubernetes-asyncio `_request_timeout`——后者用
  CancelledError 实现, 无法和 graceful shutdown 区分, 真集群实证会导致每周期误退避+重 LIST)。

> ⚠️ 部署需把 health 端口 8080 配进编排器探活 (ECS health check / K8s liveness probe 打 `GET /healthz`)。

## 部署 (ECS)

完整流程:
打包镜像 (跨目录依赖 build context = `services/`) → 推 ECR → ECS task definition
(execution role vs task role 区别) → EKS 授权 (access entry + 最小权限 RBAC)。

要点:
- worker 是**独立镜像**, 入口 `python -m worker.main` (不与 api 共享 command)。
  Dockerfile + entrypoint.sh 在本目录, RBAC 在 `deploy/rbac.yaml`。
- worker 跑在集群外 (ECS), 通过 apiserver 原生 LIST/WATCH 订阅 CR, **不装 addon**。
- 两层授权缺一不可: IAM (task role `eks:DescribeCluster` + DDB) + K8s RBAC
  (access entry 映射 group → ClusterRole 授 watch)。
- 建议 replica=1 (省资源); 需高可用可 replica=2 (DDB 条件写已保证不冲突)。
