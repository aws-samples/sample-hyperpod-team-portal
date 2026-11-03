# Dynamo 多机推理任务状态同步设计（platform-controller）

[English](dynamo-inference-sync-design.md) | **简体中文**

> 日期：2026-07-12
> 范围：在 `services/platform-controller`（Go, controller-runtime）新增一路 reconciler，
> watch NVIDIA Dynamo 的 `DynamoGraphDeployment` + 关联 Kueue `Workload`，
> 把任务状态**正确同步到 DynamoDB `ResourceIndex`**。
> **本次只负责数据同步（写 DDB）。** 读 API、response builder、router、任务列表、创建任务、
> 排队页面展示等，由 Dynamo 任务模块另行实现，不在本设计范围。
> 依据：Dynamo 官方 CRD manifest + 真实 CR + 真集群 `eks-hypd-demo`（ns `hyperpod-ns-demo`）实测。

---

## 0. 背景与关键实测事实

HyperPod 单机推理走 SageMaker inference operator（`InferenceEndpointConfig`）。**多机推理改用 NVIDIA Dynamo operator**，用户提交 `DynamoGraphDeployment`（DGD, `nvidia.com/v1beta1`）。集群实测拓扑（`grove.install=true` / `kai-scheduler.install=false`）：

```
DynamoGraphDeployment            (nvidia.com/v1beta1, status.state)
  └─ PodCliqueSet (grove.io)
       └─ PodCliqueScalingGroup  (多机 worker component)
            └─ PodClique         (leader / worker 各一个)
                 └─ Pod          (owner of ↓)
                      └─ Kueue Workload  pod-<podname>-<hash>  (owner = Pod)
  └─ PodGang (scheduler.grove.io) (gang 调度单元)
```

关键事实（全部真集群实测）：
1. **Dynamo 用 Kueue 调度**：Kueue label 由用户写在 DGD `spec.labels`（`kueue.x-k8s.io/queue-name`、可选 `priority-class`），operator 透传到所有子资源（Pod）。Grove 管 gang 编排、Kueue 管 admission。
2. **每个 Pod 一个独立 Kueue Workload**（owner=Pod，`podSets=main count=1`），一个 DGD 有多个 Workload。**不是** 1 CR ≈ 1 Workload。
3. **Workload 自身 labels 只有 `kueue.x-k8s.io/job-uid`**（=owner pod uid），DGD 名**未透传到 Workload**。反查 DGD 必须经 owner Pod。
4. **Pod 带 `nvidia.com/dynamo-graph-deployment-name=<dgd>` label**，可一次 list 出某 DGD 的全部 Pod（实测精确命中 3 个）。
5. DGD `status.state` 4 态：`initializing / pending / successful / failed`；`status.conditions[type=Ready]`；`status.components{}`（component 级，非 pod 级）。
6. **部分 admit 死锁**：gang 里只要一个 Workload admit 不了（配额不足），PodGang 停 `Pending`，DGD 停 `pending`，已 admit 的 Pod 空占资源。单个 Workload 的 admit 状态**不代表**任务状态。

---

## 1. 目标与非目标

**目标**：新增 dynamo reconciler，把以下字段正确同步进 `ResourceIndex` 的 `metadata`：
- `phase` — 如实反映 DGD `status.state`
- `kueue_status` — 多 Workload 聚合出的单一六态（取“最落后”）
- `status_detail` — DGD 原始 `status`（state/components/conditions 原样，与训练/推理/开发机对称）
- `active_ws` — 任务是否还占用资源（稀疏 GSI 联动）

**非目标（本次不做）**：
- 任何读 API / response builder / router / 任务列表 / 创建任务接口
- 任务总览页面、排队区页面展示
- `positionInLocalQueue` 排队位次的计算与落库（controller 现无此能力，留待后续按需实现）
- Grove 资源（PodClique/PCSG/PodGang）的 watch（x/y 改由 Workload 聚合，见 §4）

---

## 2. 架构：复用现有 CRReconciler 的第 4 路

platform-controller 现有一个通用 `CRReconciler`（`internal/controller/reconciler.go`），在 `SetupAll`（`internal/controller/setup.go`）实例化 3 次（train / inference / dev）。**新增第 4 路 `dynamo`**，完全套用现有模式：

- **主 watch = DGD**：`For(gvk.DynamoGraph)`。DGD 事件驱动 reconcile。
- **关联 watch = Workload**：`Watches(Workload, EnqueueRequestsFromMapFunc(mapping.WorkloadToCR(...)))` —— 与现有推理/开发机（owner=Pod，2 跳）同构。Workload 事件 → owner Pod → 读 `dynamo-graph-deployment-name` label → 触发对应 DGD reconcile。

这天然满足“watch CR + watch workload”的双 watch 需求，不需要新造 watcher。

Reconcile 5 步沿用现有循环：读 CR（NotFound→软删）→ resolveIDs → **fetchWorkloads（复数，新增）** → derive.Derive → writer.UpsertStatus。写入层（`ddb/writer.go`）的部分更新 + dedup + rv 闸门 + **active_ws / kueue_status 旁路**全部类型无关，直接复用。

---

## 3. Workload 关联：正查（聚合）与反查（触发）

这是本设计相对现有代码的**唯一结构性新增**。现有 `fetchWorkload` 取“最新单个 Workload”，对 Dynamo 多 Workload 不成立。

**反查（Workload 事件 → DGD，触发 reconcile）** — `mapping.WorkloadToCR` 加 Dynamo 分支：
- Workload → owner Pod（`ownerReferences`，1 层）→ 读 Pod label `nvidia.com/dynamo-graph-deployment-name` = DGD 名 → 入队该 DGD。
- 与现有 2 跳 mapping 同构，仅 Pod label key 不同。

**正查（DGD → 所有 Workload，用于聚合）** — 新增 `fetchWorkloads`（复数）。**全程走 manager cache 内存读，零额外 API 调用**：既然 `Watches(Workload)` 已把这些 Workload informer 进 manager cache，且 controller-runtime 的 client `List` 默认读 cache，聚合完全在内存完成。步骤：
1. cache `List` Pod，`MatchingLabels{nvidia.com/dynamo-graph-deployment-name: <dgd-name>}` → 拿到该 DGD 全部 Pod（实测精确，含 frontend + 各 worker），收集其 `uid` 集合。
2. cache `List` 本 namespace 的 Workload → 在内存按 `kueue.x-k8s.io/job-uid ∈ uid集合` 过滤出属于该 DGD 的全部 Workload（pod-uid join）。
3. 收集全部 Workload 交给派生层聚合。

> 关键：Workload 自身**无 DGD label**（实测只有 job-uid），无法一步过滤，必须先经 Pod 建立 uid↔DGD 归属。但两步都是 cache 内存读，无 API 往返。
> 备选（已否决）：直接用 DGD label 一步 list Workload —— 实测 Workload 无 DGD label，不可行。

---

## 4. 状态派生规则（`derive/derive_dynamo.go`，新增）

### phase（如实反映 CR）
- 直接取 DGD `status.state`（`initializing/pending/successful/failed`），**不归一化**。缺失回退 `initializing`（CRD 默认值）。

### kueue_status（多 Workload 聚合，取“最落后”）
1. 对每个子 Workload 跑现有 `deriveKueueFromWorkload()` 得单个六态。
2. **聚合 = 取最落后**：新增 `aggregateKueue(workloads)`，复用现有 `kueuePriority`（`Finished>Evicted>PodsReady>Admitted>QuotaReserved`），取**优先级最低（最不进展）**的那个。规则：只要有一个 `Queued` → 任务 `Queued`；否则有 `QuotaReserved` → `QuotaReserved`；全部 `Admitted`（含 PodsReady）才算就绪。
3. 一个 Workload 都查不到，且 DGD 处于终态集（见下） → 返回 `Finished`；否则返回 `""`（冻结信号，写入层保持 DDB 旧值，复用现有语义）。

> **实测关键（2026-07-13, dynamo-probe successful 40h）**：Dynamo 的 Kueue Workload **只有 `QuotaReserved` + `Admitted` 两个 condition，永远不出现 `PodsReady`**（这套 Grove+Kueue pod-integration 未启用 PodsReady tracking）。因此：
> - **Dynamo 任务"就绪"态的 kueue_status 封顶是 `Admitted`**（不会到 PodsReady），聚合逻辑不能等 PodsReady 作为就绪信号。
> - Kueue 六态对 Dynamo 只反映到"资源已分配/已 admit"这一层；**"服务真正 ready 能收流量"要看 DGD `status.state=successful` / `conditions[Ready]=True`**，不是 Kueue。这再次印证 phase 与 kueue_status 是两个正交维度。
> - 三个 Workload（frontend + ldr + wkr）实测均 `QuotaReserved=True, Admitted=True` → 聚合结果 = `Admitted`。job-uid 实测精确等于 owner pod uid（如 ldr pod uid `98fe6ca0…` = 其 workload job-uid），聚合 join 键成立。

### status_detail（存 DGD 原始 status，与训练/推理/开发机对称）
**只存 DGD 的原始 `status`**（`state` / `components` / `conditions` / `observedGeneration` 原样），每次 CR 变化时刷新——与现有 `derive_training`/`derive_inference`/`derive_dev` 把 CR 原始状态片段塞进 `status_detail` 完全同一套路。实测 successful 态的 status 结构（原样落库）：
```json
{
  "state": "successful",
  "components": {
    "Frontend": {"componentKind":"PodClique","readyReplicas":1,"replicas":1,"updatedReplicas":1,"componentNames":["dynamo-probe-0-frontend"]},
    "worker":   {"componentKind":"PodCliqueScalingGroup","availableReplicas":1,"replicas":1,"updatedReplicas":1,"componentNames":["dynamo-probe-0-worker"]}
  },
  "conditions": [{"type":"Ready","status":"True","reason":"all_resources_are_ready","message":"All resources are ready","lastTransitionTime":"..."}],
  "observedGeneration": 1
}
```

**不落**加工信息（admitted x/y、各 Workload 明细、卡住 message、各 WL 排队位次）。这些由读端需要时实时查 Kueue/Pod，不进 DDB。理由：与现有资源类型对称（status_detail 只存 CR 原始状态），且这类明细易变、落库有时效滞后风险。

> 注意：`status.components` 是 **component 级**（worker=PodCliqueScalingGroup 只显示 1 个 gang 组 `replicas:1`，看不到底层 3 个 Pod），且字段随 componentKind 变（PodClique 有 `readyReplicas`，PCSG 只有 `availableReplicas`）。因此**它不能用来算 pod 级 x/y**——但作为原始 status 原样存储没问题，读端自行解读。

### 终态集
- DGD `status.state == failed` 视为终态候选（详见 §5 的 active_ws 判定）。
- `successful` 是“部署成功、长期运行中”的服务态，**不是**终态（推理服务不自然结束）。

---

## 5. active_ws（是否还占资源）

复用现有稀疏 GSI 机制（`writer.go` 的 `ActiveSet/ActiveRemove/ActiveFreeze` 三态 + rv 旁路）。

| DGD 情况 | active_ws | 理由 |
|---|---|---|
| initializing / pending / successful | **保留**（ActiveSet） | 在跑或在排队，占/试图占资源 |
| pending 且部分 admit 卡死 | **保留** | 已 admit 的 Pod 实际占着资源 |
| failed | **⚠️ 待实测定稿**（见下） | 不能只看聚合 kueue_status，需下钻查真实 Pod |
| 用户停止 / 删除 DGD | 删除（ActiveRemove） | MarkDeleted |

**failed 的 active_ws 判定（待实测定稿，不能只靠聚合 kueue_status）**：

初版设计曾假设“failed 时只要有活跃 Workload，聚合结果自然是活跃态，active_ws 自动保留，无需额外判断”——**这个推断不成立**。failed 是 Dynamo 里语义最不确定的状态：
- Workload 可能已被 operator 清掉（fetchWorkloads 查不到 → 聚合返回冻结/Finished），但底层 **Pod 其实还在 Running/Pending 占着卡**；
- 反之 Workload 还在但 Pod 已退出。

因此 failed 的占资源判定**必须下钻查真实 Pod**，参照现有**训练**的占卡逻辑 —— `derive_training.go` 的 `trainOccupyingActive` + `activeByLivePod`（去 List 该任务的 Pod，看是否有 Running/Pending 的 Pod，据此决定 ActiveSet/ActiveRemove）。Dynamo 应复用同一思路：failed 时 List 该 DGD 的 Pod（同 §3 的 cache list Pod），有 Running/Pending Pod → active_ws 保留；全部退出 → kueue_status=Finished + active_ws 删除。

**具体规则待观察真实 failed DGD 后定稿**（见 §7）：需实测 failed 时 DGD.state / Workload / Pod 三者的真实状态组合，才能确定下钻判据（查 Pod phase 是否足够，还是要看 PodClique）。在定稿前，实现上先复用训练的 `activeByLivePod` 模式作为占位。

---

## 6. 要改 / 新增的文件清单（全部在 platform-controller）

| 文件 | 改动 |
|---|---|
| `internal/gvk/gvk.go` | 新增 `DynamoGraph` GVK（`nvidia.com/v1beta1/DynamoGraphDeployment`）；新增 Pod label 常量 `nvidia.com/dynamo-graph-deployment-name`；按需加入 `AllCRs` |
| `internal/controller/setup.go` | spec 表加一行 `{gvk.DynamoGraph, "dynamo", "dynamo-controller", false}`；Workload 关联走 `Watches + mapping.WorkloadToCR`（2 跳） |
| `internal/controller/reconciler.go` | `fetchWorkload` 加 Dynamo case → 调新增的 **`fetchWorkloads`（复数）**；Dynamo 走 cache list Pod（按 DGD label）+ cache list Workload → 内存 pod-uid join（零额外 API，见 §3）。failed 下钻用的 Pod 列表复用同一次 cache list |
| `internal/controller/associate.go` | 加 Dynamo 的 Pod label key（`nvidia.com/dynamo-graph-deployment-name`） |
| `internal/controller/resolveids.go` | 加 Dynamo 的 resource_id / workspace_id label 解析（注入的 `platform.hyperpod.io/inference-id`、`workspace-id`；缺失则跳过，与现有一致） |
| `internal/mapping/mapping.go` | `CRNameLabelFor` 加 Dynamo Kind → Pod label case |
| `internal/derive/derive.go` | `Derive` 分派加 Dynamo case |
| `internal/derive/derive_dynamo.go` | **新建**：phase / 聚合 kueue_status / status_detail / active_ws 派生 |
| `internal/derive/kueue.go` | 新增 `aggregateKueue(workloads)`（取最落后，复用 `kueuePriority`） |
| `deploy/business-cluster-rbac.yaml` | ClusterRole 加 `apiGroups:["nvidia.com"] resources:["dynamographdeployments"] verbs:[get,list,watch]`（Workload/Pod 权限已存在） |

**不改**：`ddb/writer.go`（部分更新/dedup/rv 闸门/active_ws 旁路全类型无关）；表结构（由 platform-api 侧 `tables.py` 定义，controller 只按约定写字段——需在 platform-api 的 `tables.py` 加 `RESOURCE_TYPE_DYNAMO` 常量 + `VALID_TYPES`，这属于读端协调项，本次仅记录依赖）。

> **跨仓依赖提示**：`resource_type = "dynamo"` 的字符串约定，controller 直接写即可（controller 不校验 VALID_TYPES，那是 platform-api 读端的事）。但为让读端不拒绝，需在 platform-api `tables.py::VALID_TYPES` 加入 `dynamo`。此为协调项，非本次代码交付。

---

## 7. 未决 / 需实测确认项

1. ~~**resolveIDs 的 label 注入**~~ **✅ 已解（2026-07-14，平台创建链实测 `test-multi-01-yr1h08ude5`）**：平台前端创建的 DGD 在 `metadata.labels`（正是现有 resolveIDs 读的位置 `cr.GetLabels()`）已注入全套：
   - `platform.hyperpod.io/dynamo-id` = resource_id（**注意 key 是 `dynamo-id`，非 `inference-id`——印证独立类型 `dynamo`**）
   - `platform.hyperpod.io/workspace-id` = workspace_id
   - `platform.hyperpod.io/creator-id` = creator（建 stub 时用）
   - 额外 `platform.hyperpod.io/framework`（sglang）、`kueue.x-k8s.io/priority-class`（实测 `common-priority`，与现有推理链一致）
   → resolveIDs 只需加 `resourceIDLabelFor("DynamoGraphDeployment") = "platform.hyperpod.io/dynamo-id"`，workspace-id 复用现有 `labelWorkspaceID`。
2. **failed 真实行为（唯一剩余阻塞，阻塞 §5 定稿）**：实测只观察到 `pending`/`successful`，**未捕获 `failed` 实例**。§5 的 active_ws 判定明确不能只看聚合 kueue_status，需下钻查真实 Pod（参照训练 `activeByLivePod`）。**必须造一个 failed DGD（错镜像/错命令）实地观察 failed 时 DGD.state / Workload / Pod 三者的真实状态组合**，才能定稿下钻判据（查 Pod phase 是否够，还是要看 PodClique / operator 是否重启 Pod）。定稿前实现用训练的占卡模式占位。
3. ~~**resource_id 取值**~~ **✅ 已解**：用 `platform.hyperpod.io/dynamo-id` label 值（见第 1 项），与现有 label 路径一致，无需 uid/name 回退。
4. **kueue_status 聚合范围是否含 Frontend**：当前聚合含该 DGD 全部 Workload（frontend + workers）。Frontend 是单机、通常先就绪；若某场景下 Frontend 单独排队会不会不合理地把整任务拖成 Queued，需实测判断。若要只按 worker 聚合，可在 fetchWorkloads 按 `nvidia.com/dynamo-component=worker` 过滤。默认含全部。

---

## 8. 验证方式

- 单测：`derive_dynamo_test.go` 覆盖聚合规则（全 admitted、部分 admit、全排队、含 Finished）、failed 的占卡下钻（有 live Pod / 无 live Pod 两种）、phase 映射。
- 真集群：对 `dynamo-probe`（successful）验证 phase=successful、kueue_status=`Admitted`（实测三 WL 全 QuotaReserved+Admitted，无 PodsReady）、status_detail=原始 status 原样、active_ws 保留；重建一个配额不足的 gang（如 gangtest）验证 phase=pending + kueue_status=QuotaReserved/Queued 正确写入 DDB；**造一个 failed DGD 观察并定稿 §5 的 active_ws 下钻规则**。
- DryRun：controller 支持 `writer.DryRun`，先干跑核对 UpdateItem 表达式再落库。
