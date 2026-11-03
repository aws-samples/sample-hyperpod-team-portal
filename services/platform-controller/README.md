# platform-controller (Go / controller-runtime)

跨集群 **projection controller**: watch 被管集群 (集群 Y, hyperpod) 的三种业务 CR
+ Kueue Workload (可选 Pod), 派生状态单向投影到 DynamoDB。本进程跑在集群 X,
**不在被管集群放任何东西** (满足"被管集群零额外 controller"约束)。

是现有 Python `services/platform-worker` 的演进目标 — 用框架取代手写的
watch/重连/分页/dedup/backfill/supervisor (这些 controller-runtime 全内置),
业务逻辑 (派生六态 / 写 DDB / owner 映射) 从 Python 翻译过来。

## 为什么用框架 (它替你做了什么)

| 现有 Python worker 手写的 | controller-runtime 内置 |
|---|---|
| watch 循环 / rv 续传 / 410·401 重连 / 超时 | informer (Reflector) |
| 冷启动分页 LIST | informer 启动时 LIST→灌 cache |
| dedup 去重 | WorkQueue (同 key 合并) |
| backfill 退避重试 | WorkQueue rate limiter |
| supervisor 单路自愈 / watchdog | Manager + leader election |
| 每事件跨集群查 Workload | Workload 进 informer cache, 内存读 |
| **派生六态 / phase** | ❌ 你的业务 (internal/derive) |
| **写 DDB / 部分更新 / active_ws** | ❌ 你的业务 (internal/ddb) |
| **Workload/Pod → CR owner 映射 (2跳)** | ⚠️ 框架给挂载点, 映射逻辑你写 (internal/mapping) |

## 版本 (2026-06 核实)

| 模块 | 版本 | 来源 |
|---|---|---|
| Go | 1.26.4 | go.dev release |
| sigs.k8s.io/controller-runtime | v0.24.1 | pkg.go.dev + 其 go.mod |
| k8s.io/{client-go,apimachinery,api} | v0.36.0 | controller-runtime v0.24.1 的 go.mod |
| github.com/aws/aws-sdk-go-v2 (core) | v1.42.0 | pkg.go.dev |

> go.mod 里的 aws-sdk 子模块版本是近期稳定起点。装 Go 后:
> ```
> go mod tidy        # 锁定/补全 go.sum
> go get -u ./...    # 升级到当下最新补丁 (可选)
> go build ./...
> ```

## 目录

```
cmd/controller/main.go       入口: 跨集群 config + Manager + leader election 分离 + DDB client  [✅ 完整]
internal/config/             环境变量配置                                                      [✅ 完整]
internal/gvk/                三种 CR + Workload + Pod 坐标 (单一真相源)                          [✅ 完整]
internal/controller/         reconcile (读 cache→派生→写 DDB) + setup (注册三路 watch)          [✅ 骨架, 几处 TODO]
internal/derive/             派生六态/phase                                                    [⛏ 你补业务]
internal/mapping/            Workload/Pod → CR owner 映射                                       [⛏ 你补业务]
internal/ddb/                DDB 部分更新 + dedup + active_ws 联动                              [⛏ 你补业务]
```

## 你要补的业务 (都有对应的 Python 源可翻译)

1. **internal/derive/derive.go · `Derive()`**
   翻译 `worker/phase.py` + `shared/kueue_status.py` + 三个 informer 的 `derive_status_md`。
   保留所有设计决策 (六态优先级 / KueueStatus 空=保持旧值 / CR 终态短路 / cleanPodPolicy 占卡预判)。

2. **internal/mapping/mapping.go · `WorkloadToCR()` (+`PodToCR`)**
   2 跳 owner 映射 (Workload→Pod→CR)。**前置: 先 kubectl 确认真实 owner 链** (见下)。

3. **internal/ddb/writer.go · `UpsertStatus`/`CreateStub`/`MarkDeleted`**
   翻译 `repositories/resource_index.py` 的 `update_status_if_changed`/`_build_status_update_expr`/
   `create_stub`/`mark_deleted`。保持: 部分更新只动派生字段、dedup、active_ws 联动、kueue_status
   空不覆盖、主键 workspace_id + "<type>#<id>"。

4. **internal/controller/reconciler.go**
   - `resolveIDs` (setup.go 里, 每类 CR 一个): label 优先 + namespace 反推 ws (翻译 `resolve_ids`)
   - `fetchAssociated`: 1跳/2跳 从 cache list Workload/Pod
   - `handleDeleted`: CR 删除后定位 DDB 行 (需 CR name→ws/id 的推断或本地索引)

## 上线前必须先确认的事实

- **真实 owner 链**: 推理/开发机 Workload 的 `ownerReferences` 到底是不是 Workload→Pod→CR?
  ```
  kubectl get workload <名> -n <ns> -o jsonpath='{.metadata.ownerReferences}'
  ```
  这决定 mapping 怎么写。链不规则 (有的有有的没有 owner) 要特殊处理。
- **被管集群 RBAC**: 跨集群身份要有 三种CR + Workload + Pod 的 list/watch 权限 (只读)。
- **cache 内存**: 40000 CR 全缓存进内存, 用 `WATCH_LABEL_SELECTOR` 只 watch 带平台 label 的对象控内存
  (TODO: 在 main.go 的 cache.Options.ByObject 里按 selector 过滤; 当前骨架未接, 见下)。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `BUSINESS_KUBECONFIG` | ✅ | 业务集群 Y 的 kubeconfig (含 `aws eks get-token` exec → 自动刷 token); Pod 里由 entrypoint 生成 |
| `PLATFORM_KUBECONFIG` | | 平台集群 X 的 kubeconfig; 留空用 in-cluster (controller 跑在 X 内时); Pod 里留空 |
| `BUSINESS_EKS_CLUSTER_NAME` | (Pod) | 业务集群名; Pod 部署只需传这个, entrypoint 用它生成 `BUSINESS_KUBECONFIG` |
| `DDB_TABLE` | ✅ | ResourceIndex 表名 |
| `AWS_REGION` | | 默认 us-west-2 |
| `ENABLE_LEADER_ELECTION` | | 默认 true |
| `WATCH_LABEL_SELECTOR` | | 控 cache 内存, 如 `platform.hyperpod.io/managed=true` |

## 已知未接的脚手架点 (骨架阶段故意留)

- cache label selector 还没接到 `WATCH_LABEL_SELECTOR` (main.go 的 cache.Options.ByObject)
- `WorkloadToCR` 当前对训练用 builder.Owns 更省 (1跳框架自动); 是否保留 mapping 路自行决定
