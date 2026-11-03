# FSx 挂载机制详解 · PV / PVC / CR 逐行说明

[English](fsx-mount-pv-pvc-cr-explained.md) | **简体中文**

> 面向：技术评审 / 运维交接
> 日期：2026-07-17
> 内容：平台把共享 FSx for Lustre 的一个子目录挂进开发机/训练容器时，生成的
> PersistentVolume、PersistentVolumeClaim、以及 Workspace CR 三者的每一行含义，
> 及三者如何协作、读写/只读权限如何实现。

以 team-a 的**读写(rw)**挂载为例（工作空间 id `90d7eb44…`，FSx `fs-0c0b…`，子目录 `team-a`）。

---

## 0. 三者关系总览

```
Workspace CR (开发机)            PVC                          PV                        FSx
spec.volumes:                    pvc-ws-fsx-team-a-data-rw     pv-...-team-a-data-rw     fs-0c0b
  persistentVolumeClaimName ───► name        ◄── volumeName ──► claimRef 指回 PVC
  mountPath: /fsx/team-a-data                                   csi.mountname:            /team-a
  runAsGroup: 5001 ◄─ 权限靠 gid                                  2no6nb4v/team-a  ────────► 子目录
                                                                mountOptions: [](rw)
```

- **PV ↔ PVC**：严格 **1:1**，且双向锁定（PV 的 `claimRef` + PVC 的 `volumeName` 互相点名）。
- **PVC ↔ Pod**：**1:多**（accessMode=ReadWriteMany，多个开发机/训练可同时挂同一 PVC）。
- **PV/PVC ↔ FSx 子目录**：多套 PV/PVC 可指向同一子目录（如 rw / ro 两套），但每对 PV-PVC 仍是 1:1。

---

## 1. PersistentVolume（PV）— “这块存储实际在哪、怎么连”

```yaml
apiVersion: v1
kind: PersistentVolume                          # 集群级资源, 不属于任何 namespace
metadata:
  name: pv-ws-90d7eb44-...-fsx-team-a-data-rw   # PV 名. 格式 pv-ws-{工作空间id}-fsx-{挂载id}-{rw|ro}
                                                # 带 ws_id + access 保证全集群唯一
  labels:
    hyperpod.io/managed: "true"                 # 平台自建标记 (区分手动建的, 便于筛选/清理)
    hyperpod.io/workspace: team-a               # 属于哪个工作空间 (人看的)
    hyperpod.io/filesystem: fs-0c0b2e...        # 属于哪块 FSx 文件系统
  annotations:
    hyperpod.io/subdir: team-a                  # 记录挂的是 FSx 根下哪个子目录 (平台自用元数据)
spec:
  capacity:
    storage: 1200Gi                             # 声明容量. FSx 不真按这个限 (Lustre 是共享池),
                                                # 纯占位 (K8s 要求 PV 必须声明容量)
  volumeMode: Filesystem                        # 以文件系统方式挂 (对应 Block=裸块设备). FSx 用 Filesystem
  accessModes: [ReadWriteMany]                  # RWX: 允许多个节点/Pod 同时读写.
                                                # Lustre 天生支持多客户端并发, 所以是 Many (不是 RWO)
  persistentVolumeReclaimPolicy: Retain         # PVC 删除后 PV 的处理策略:
                                                # Retain=保留不动 (FSx 数据不删, 只解绑).
                                                # 绝不能用 Delete — 会连底层 FSx 数据一起删
  storageClassName: fsx-sc                       # 存储类名. 静态绑定 (PV 已手动建好),
                                                # 此字段仅用于和 PVC 对号 (两边要一致)
  mountOptions: []                              # rw 挂载: 空. ro 挂载时为 ["ro"]
                                                # Lustre CSI 上只有 mountOptions:[ro] 能真正拦写,
                                                # csi.readOnly 字段无效 (POC 验证过)
  csi:                                          # 用 CSI driver 连真实存储
    driver: fsx.csi.aws.com                     # AWS FSx CSI driver
    volumeHandle: fs-0c0b2e...-90d7eb44-team-a-data-rw
                                                # CSI 眼里这个卷的唯一标识.
                                                # 格式 {fs-id}-{ws-id}-{挂载id}-{access}.
                                                # ⚠️ 必须全集群唯一: 同块 FSx 被多个 PV 挂时,
                                                #   若都用裸 fs-id, CSI 会当成同一个卷, 第二个挂不上.
                                                #   拼上 ws+挂载id+access 错开
    volumeAttributes:
      dnsname: fs-0c0b2e....fsx.us-west-2.amazonaws.com
                                                # FSx 的网络地址 (客户端连这个)
      mountname: 2no6nb4v/team-a                # 关键! Lustre 挂载点 + 子目录.
                                                # 2no6nb4v = FSx 根 mountname, 拼 /team-a
                                                # → 只挂 team-a 子目录, 容器看不到 FSx 根
                                                #   (其他 team 的目录), 实现目录隔离.
                                                # 不能用 pod subPath — operator 会 prune 掉
  claimRef:                                     # 反向绑定: 指定这个 PV 只能被哪个 PVC 用
    namespace: hyperpod-ns-demo              # 该 PVC 所在 namespace
    name: pvc-ws-fsx-team-a-data-rw             # 该 PVC 名字.
                                                # 有 claimRef 后, 别的 ns/PVC 抢不走这个 PV
```

---

## 2. PersistentVolumeClaim（PVC）— “我要用那块存储的申请单”

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pvc-ws-fsx-team-a-data-rw              # PVC 名. 格式 pvc-ws-fsx-{挂载id}-{rw|ro}.
                                                # CR 引用的就是这个名字
  namespace: hyperpod-ns-demo               # PVC 是 namespace 级 (和用它的 Pod 同 ns)
  labels:                                       # 同 PV 的标记, 便于筛选/管理
    hyperpod.io/managed: "true"
    hyperpod.io/workspace: team-a
    hyperpod.io/filesystem: fs-0c0b2e...
spec:
  accessModes: [ReadWriteMany]                  # 要和 PV 的 accessModes 匹配才能绑
  storageClassName: fsx-sc                       # 要和 PV 的 storageClassName 一致
  resources:
    requests:
      storage: 1200Gi                           # 申请容量, 要 ≤ PV 的 capacity (这里相等)
  volumeName: pv-ws-90d7eb44-...-fsx-team-a-data-rw
                                                # 显式点名要绑哪个 PV (静态绑定).
                                                # 配合 PV 的 claimRef 双向锁定, 一一对应,
                                                # 不走动态制备 (不会自动新建 PV)
```

**PV ↔ PVC 双向绑定**：PV 的 `claimRef` 指向 PVC，PVC 的 `volumeName` 指向 PV —— 互相点名，锁死配对。

---

## 3. Workspace CR（开发机）— “这个开发机挂哪些 PVC、以谁的身份跑”

```yaml
apiVersion: workspace.jupyter.org/v1alpha1
kind: Workspace                                 # SageMaker Spaces 的开发机 CR
metadata:
  name: alicedev01-th3idttrvp                  # k8s 资源名 (用户名 + 随机后缀保唯一)
  namespace: hyperpod-ns-demo
spec:
  # ... (镜像 / 资源 / 模板等其他字段略) ...

  # ── 存储挂载: 引用 PVC ──
  volumes:
  - name: vm-fsx-team-a-data                    # volume 名 (按 mount_path 生成的 slug)
    mountPath: /fsx/team-a-data                 # 容器里挂到哪个路径 (用户在容器内看到的路径)
    persistentVolumeClaimName: pvc-ws-fsx-team-a-data-rw
                                                # 引用哪个 PVC. 这是 Workspace CRD 的自定义字段
                                                # (非标准 Pod 语法). rw/ro 由后端按授权 access 选

  # ── 权限 / 身份: 以谁的身份跑、属于哪些组 ──
  containerSecurityContext:                     # 只作用主容器 (workspace), 不影响 ssm sidecar
    runAsUser: 1000                             # 进程以 uid 1000 跑 (sagemaker-user, 非 root)
    runAsGroup: 5001                            # 进程主组 = 5001 (= 该 ws 的 primary_gid = team-a 的 gid).
                                                # 新建文件默认属这个组
  podSecurityContext:                           # Pod 级 (作用于本 Pod 的所有卷, 不针对单个卷)
    fsGroup: 5001                               # 主 gid 的"兜底": 只能填一个值, K8s 对所有卷根目录
                                                # 尝试 chown 到这个组. 单卷/主卷有用; 但一个 Pod 挂了
                                                # 多个不同 gid 的目录时, 它对不上其余目录 (见下方说明),
                                                # 真正让多目录可写的是 supplementalGroups + 目录自身 setgid/gid
    supplementalGroups: [5001, 5002]            # 附加组: 该开发机挂的所有目录的 gid 都列进来.
                                                # 进程"同时属于"这些组 → 配合每个目录自身的 setgid+gid
                                                # (drwxrws--- 创建时设死), 各目录都能按组权限读写.
                                                # 如同时挂 team-a(5001) + share 来的 team-b(5002),
                                                # 进程属 5001 和 5002 两个组, 两个目录都能写
```

> **fsGroup 与 supplementalGroups 的分工（重要）**
> - `fsGroup` 是 **Pod 级、只能一个值、作用于所有卷**——它不针对某个卷（这也是它和 `volumes` 平级的原因）。
>   一个 Pod 挂多个不同 gid 的目录时，fsGroup 那一个值只能对上其中一个（主 gid），其余目录靠它对不上。
>   所以它更像是**主 gid 的兜底**。
> - **真正保证"进程能写多个不同 gid 目录"的，是**：
>   1. **`supplementalGroups`**——让进程同时属于所有相关的组（5001、5002…）；
>   2. **目录本身的 setgid + gid**（创建目录时 `chmod 2770 + chown :<gid>` 设死，即 `drwxrws--- gid=xxxx`）——每个目录自己的属组是对的，不依赖 fsGroup。
>   进程属于该目录的 gid 组 + 目录组可写 → 就能写，与 fsGroup 无关。

**operator 翻译**：SageMaker Spaces operator 读此 CR，把 `spec.volumes[].persistentVolumeClaimName`
翻译成真正 Pod 的标准写法（自动生成，无需手写）：

```yaml
volumes:
- name: vm-fsx-team-a-data
  persistentVolumeClaim: { claimName: pvc-ws-fsx-team-a-data-rw }
containers:
- volumeMounts:
  - { name: vm-fsx-team-a-data, mountPath: /fsx/team-a-data }
  securityContext: { runAsUser: 1000, runAsGroup: 5001 }
```

---

## 4. 读写 / 只读 是怎么实现的

同一个 FSx 子目录，平台建**两套 PV/PVC**：

| PVC | 对应 PV 的 mountOptions | 用途 |
|---|---|---|
| `...-team-a-data-rw` | 空 | 读写 |
| `...-team-a-data-ro` | `["ro"]` | 只读（Lustre CSI 在挂载层拦写）|

授权记录（MountPermissions 表）里 `pvc_name_rw` 和 `pvc_name_ro` **两个名都存**，创建资源时后端按该用户的 `access` 选用哪一个：
- `access = rw` → 挂 `pvc_name_rw`（那套无 ro option 的 PV）
- `access = ro` → 挂 `pvc_name_ro`（那套带 `mountOptions:[ro]` 的 PV）

**权限有两道闸，都要通过才能写：**

| 闸 | 位置 | 作用 |
|---|---|---|
| 1. PV 挂载层 | PV 的 `mountOptions:[ro]` | ro 挂载整体只读；rw 挂载放行 |
| 2. POSIX 组权限 | CR 的 `runAsGroup`/`supplementalGroups` + 目录的 `setgid + gid`（drwxrws---）| 进程属于目录的 gid 组 → 按组权限读写 |

只读挂载 = 第 1 道闸拦（用 ro 那套 PV/PVC）；正常读写 = 两道闸都放行（rw 那套 PVC + 进程在该 gid 组）。

---

## 5. 关键设计点小结

| 点 | 说明 |
|---|---|
| **PV↔PVC 1:1** | 双向锁定（claimRef + volumeName），别的 ns/PVC 抢不走 |
| **目录隔离** | 靠 PV 的 `csi.mountname = <lustre-mount>/<subdir>`，只挂子目录；**不能用 pod subPath**（operator 0.0.16 会 structural prune 丢弃）|
| **只读实现** | 只有 PV 的 `mountOptions:[ro]` 有效；`csi.readOnly` 在 Lustre CSI 上无效 |
| **volumeHandle 唯一** | `{fs-id}-{ws-id}-{挂载id}-{access}`，防同块 FSx 多 PV 撞车 |
| **reclaimPolicy=Retain** | 删 PVC/PV 不动 FSx 数据，共享存储必须 |
| **CR 引用 PVC** | Workspace CRD 用自定义字段 `spec.volumes[].persistentVolumeClaimName`，operator 再翻译成标准 Pod volume |
| **组权限** | `runAsGroup`=ws 主 gid（新建文件的默认组）；`supplementalGroups`=所有挂载目录 gid（进程同属多组）；配合目录自身 setgid+gid（创建时设死）实现按 team 隔离读写 |
| **fsGroup 的定位** | Pod 级、只能一个值、作用所有卷——是**主 gid 的兜底**；多个不同 gid 目录的可写性靠 `supplementalGroups` + 目录自身 setgid/gid，不靠 fsGroup |
