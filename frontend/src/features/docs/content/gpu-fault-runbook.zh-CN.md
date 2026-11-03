# GPU 节点故障诊断 Runbook
## 适用平台：Capacity Block / Self-Managed EKS / SageMaker HyperPod

**版本：** 1.0 | **更新日期：** 2026-07-06

---

## 适用场景

GPU 集群中节点出现以下症状：
- 节点 NotReady / Pod CrashLoopBackOff
- `nvidia-smi` 显示 ERR! 或部分 GPU 不可用
- Xid 错误（31/38/94/137/145）
- GPU requires reset / FULLCHIP_RESET
- 多个 GPU 被 Fabric Manager 隔离
- 删除/重启节点后问题复现
- 同一物理 GPU UUID 反复被分配回来，并反复报错

---

## 第一步：收集基本信息

| 信息项 | 命令/来源 |
|--------|-----------|
| Instance ID | `kubectl get node <node> -o jsonpath='{.spec.providerID}'` |
| 启动时间 | `kubectl get node <node> -o jsonpath='{.metadata.creationTimestamp}'` |
| GPU 型号/数量 | `nvidia-smi --query-gpu=name,count --format=csv` |
| 症状描述 | 具体错误类型：Xid 编号？GPU requires reset？ERR!？7/8 隔离？ |
| 影响范围 | 几个 GPU 受影响？整节点 or 单 GPU？ |
| 复现频率 | 每次重启后多久复现？跨重启是否持续？ |

---

## 第二步：GPU 状态日志（⚠️ 在故障状态下、terminate 之前收集）

> **关键原则：先收集，再操作。Terminate 后数据将丢失。**

SSH 到故障节点后执行：

```bash
# GPU 整体状态
nvidia-smi

# 详细 GPU 信息（ECC、温度、功率、remapped rows）
nvidia-smi -q

# NVLink 状态
nvidia-smi nvlink --status

# NVLink 错误计数
nvidia-smi nvlink -e

# Remapped rows（判断 HBM 健康）
nvidia-smi --query-remapped-rows=gpu_uuid,remapped_rows.correctable,remapped_rows.uncorrectable,remapped_rows.pending,remapped_rows.failure --format=csv

# GPU UUID 列表（用于后续追踪物理硬件）
nvidia-smi --query-gpu=gpu_uuid,index,name,serial,temperature.gpu --format=csv

# 完整 NVIDIA 诊断包（提交给 AWS/NVIDIA 的关键文件）
sudo nvidia-bug-report.sh
```

---

## 第三步：系统日志

```bash
# dmesg 中 nvidia/Xid/NVLink 相关信息
dmesg | grep -i "nvrm\|xid\|nvidia\|nvlink\|reset\|bad.*register" > dmesg-nvidia.log

# 完整 dmesg
dmesg > dmesg-full.log

# Fabric Manager 日志（NVSwitch/NVLink 多 GPU 通信的关键组件）
journalctl -u nvidia-fabricmanager --since "48h ago" > fm-journal-48h.log
systemctl status nvidia-fabricmanager > fm-status.txt
```

---

## 第四步：DCGM 诊断（如已安装）

```bash
# Level 3 完整诊断（耗时约 10-15 分钟）
dcgmi diag -r 3

# 或通过 Prometheus/DCGM exporter 检查关键指标：
# DCGM_FI_DEV_XID_ERRORS > 0
# DCGM_FI_DEV_ECC_DBE_VOL_TOTAL > 0
# DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS > 0
# DCGM_FI_DEV_ROW_REMAP_FAILURE = 1
# DCGM_EXP_GPU_HEALTH_STATUS != healthy
```

---

## 第五步：快速故障分类

根据收集到的信息，对照下表判断故障类型：

| 故障类型 | 关键特征 | 影响 | 恢复方式 |
|---------|---------|------|---------|
| **A: GPU 脱离总线** | nvidia-smi 显示 ERR!; dmesg 有 `0xbad…` 毒值; FULLCHIP_RESET; 温度异常高 | 单 GPU 完全不可用，整节点废弃 | **EC2 terminate**（无软件恢复方案） |
| **B: NVLink Xid 145 FM 隔离** | 7/8 GPU 被隔离; ECC 计数全零; FM journal 有 Xid 145/137; 温度正常 | 7 GPU 不可分配，1 GPU 正常 | **重启 Fabric Manager**（<1分钟恢复） |
| **C: HBM 磨损（正常）** | uncorrectable_remapped_rows > 0; failure=No | GPU 仍可正常使用 | **继续使用，持续监控** |
| **D: HBM 耗尽** | remapping_failure=Yes | GPU 必须退役 | **EC2 terminate**（自动 degrade） |
| **E: 单 GPU Xid 94（典型 ECC）** | 单个 GPU 报 Xid 94; ECC 计数有增长; 无级联 | 单 GPU 不可用 | **EC2 stop/start 或 terminate** |
| **F: Xid 38（驱动通道错误）** | 单 GPU 报 Xid 38; 节点静默降级为 7/8 | 少 1 个 GPU | **EC2 terminate + relaunch** |
| **G: 跨主机关联故障** | 多台独立主机在秒级内触发相同错误; 相同 error signature | 多节点同时受影响 | **重启 FM（临时）; 需 NVIDIA 介入** |
| **X: 未知故障** | 不匹配以上任何 pattern | 需调查 | **保留实例，收集全部数据，开 Case 升级** |

---

## 第六步：恢复操作

### 故障 A — GPU 脱离总线 (ERR! / FULLCHIP_RESET)

```
1. 确认已收集所有诊断日志
2. 开 AWS Support Case（severity: critical）
3. 等待 Support 确认物理机隔离完成
4. Terminate 实例 → Karpenter/ASG 自动拉起替换
5. 验证新节点 8/8 GPU 正常
```

### 故障 B — NVLink Xid 145 / 多个GPU 隔离

```bash
# 重启 Fabric Manager（无需重启实例）
sudo systemctl restart nvidia-fabricmanager

# 重启 device-plugin Pod（重新枚举 GPU）
kubectl -n gpu-operator delete pod <nvidia-device-plugin-pod-on-this-node>

# 解除节点隔离
kubectl uncordon <node>

# 验证：预期在 ~1 分钟内恢复 8/8 GPU
kubectl get node <node> -o jsonpath='{.status.allocatable.nvidia\.com/gpu}'
```

### 故障 C — HBM 磨损（failure=No）

```
无需立即操作。GPU 仍可安全使用。
持续监控以下指标：
- DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS → 趋势
- DCGM_FI_DEV_ROW_REMAP_FAILURE → 一旦变为 Yes 则需 terminate

如需 reset row remap 状态：EC2 stop/start 或 terminate+relaunch 即可触发。
```

### 故障 D — HBM 耗尽 (failure=Yes)

```
1. Terminate 实例
2. EC2 健康检查会自动将该 host degrade，不会再分配给任何客户
3. Karpenter/ASG 自动拉起替换到新硬件
4. 无需手动请求隔离
```

### 故障 E/F — 单 GPU Xid 94 / Xid 38

```
1. EC2 terminate+relaunch（或 stop/start）
2. 恢复后检查 remapped_rows — 如 failure=No，GPU 安全可用
3. 如同一 UUID 反复出问题：记录 UUID，开 Case 跟进
```

### 故障 G — 跨主机关联故障

```
1. 在所有受影响节点上收集完整诊断包
2. 记录精确时间戳 + 所有实例 ID + 错误签名
3. 各节点执行：sudo systemctl restart nvidia-fabricmanager（临时恢复）
4. 立即开 Case，标注为 fleet-level 系统性问题
5. 证明关联性：相同 error code/subcode/timing 出现在不同物理主机/机架
```

### 故障 X — 未知故障处理流程

```
1. 不要猜测根因 — 视为新问题
2. 保留实例 — 不 terminate、不 reboot，直到诊断完成
3. 收集全部数据（用第八步的一键脚本）
4. 尝试非破坏性恢复（按顺序）：
   a) nvidia-smi -r（GPU reset）
   b) systemctl restart nvidia-fabricmanager
   c) 最后才考虑 reboot
   → 记录每一步的结果
5. 对照第五步分类表，看是否能归入已知 pattern
6. 如仍无法分类 → 开 Case 提交全部日志，标注"未知故障类型"
7. 通知 TAM 升级处理
```

---

## 第七步：开 Case 与升级

### 开 Case 时提供以下信息

```
Subject: GPU fault — [症状简述] — [实例类型] — [区域]
Severity: Critical（如阻塞训练）

正文包含：
- Instance ID
- GPU UUID（故障 GPU）
- 症状描述 + 时间线
- 故障类型判断（A-G/X）
- 已尝试的恢复操作及结果
- 诊断文件已上传到 Case
```

### 需要 TAM 升级的情况

- 同一 Capacity Block 反复出现故障（疑似物理硬件缺陷）
- 故障类型为 G（跨主机关联）或 X（未知）
- Support 响应超过预期时间
- 故障影响训练进度或产品发布节点

---

## 第八步：后续跟进

| 检查项 | 验证方法 |
|--------|---------|
| 新节点 GPU 全部正常 | `nvidia-smi` — 8/8 GPU 可见，无 ERR! |
| NVLink 全部 active | `nvidia-smi nvlink --status` — 全部链路有带宽 |
| 未分配到旧故障硬件 | 比对 GPU UUID — 应与故障机不同 |
| Remapped rows 干净 | `--query-remapped-rows` — 确认新节点无残留损伤 |
| Pod 正常调度 | `kubectl get pods -o wide` — GPU Pod 在新节点运行 |

---

## SageMaker HyperPod 专项补充

> 以下仅适用于 SageMaker HyperPod 托管集群。Self-managed EKS 请跳过。

### HyperPod 的自动恢复能力

HyperPod 内置 **Health Monitoring Agent (HMA)**，提供：
- GPU 健康持续监控（DCGM 级别）
- NVLink / EFA 连接性检测
- 自动标记 unhealthy → 自动排空 → 自动替换节点

**当 HMA 自动处理时：**
- 无需人工干预
- 典型恢复时间：5-15 分钟
- 验证：CloudWatch Logs `/aws/sagemaker/Clusters/<cluster-name>/HealthMonitoringAgent`

### HMA 未能检测到的故障

以下情况 HMA 可能不会自动触发替换：
- Xid 145 FM 隔离（多 GPU，实例仍 "reachable"）
- 渐进式 HBM 磨损（未达即时故障阈值）
- 新型错误 pattern（不在 HMA 检测规则中）

**这种情况下：** 按上述第二步~第六步手动诊断和恢复。

### HyperPod Deep Health Check（主动检测）

建议在大规模训练开始前主动运行：

```bash
# 触发 Deep Health Check
aws sagemaker create-cluster-node-group-action \
  --cluster-name <cluster> \
  --node-group <group> \
  --action-type DeepHealthCheck \
  --target-instances <instance-id>
```

| 检查类型 | 内容 |
|---------|------|
| InstanceHealth | GPU/PCI 验证 + DCGM 诊断 + EFA 回环 |
| InstanceConnectivity | 跨节点 NCCL 通信性能验证 |

**结果解读：**
- PASS → 硬件健康，问题在 workload/软件层
- FAIL + 具体组件 → 精确定位故障（GPU N / NVLink link M / EFA port X）

### HyperPod 手动替换节点

**Slurm 集群：**
```bash
aws sagemaker update-cluster \
  --cluster-name <cluster> \
  --instance-groups '[{
    "InstanceGroupName":"<group>",
    "InstanceCount":<N>,
    "Action":"Replace",
    "TargetInstances":["<instance-id>"]
  }]'
```

**EKS-based HyperPod：**
- Cordon + drain 节点
- 删除对应的 MachineDeployment/NodeClaim
- HyperPod controller 自动 provision 替换

### HyperPod Lifecycle Scripts 自愈建议

添加到 lifecycle scripts 中：

```bash
# on-node-start：入池前验证 GPU 健康
nvidia-smi -q | grep -i "remapping failure" | grep -i "yes" && exit 1

# on-fault-detected：替换前自动收集诊断
/opt/gpu-diag-collect.sh
aws s3 cp /tmp/gpu-diag-*.tar.gz s3://<your-bucket>/diagnostics/
```

### HyperPod 特有故障：GPU 启动循环（Boot Loop）

**症状：**
- 多台实例 LCC（Lifecycle Configuration）反复执行失败
- Host Agent 日志中出现 DCGM exit code 226
- HMA 检测到故障 → 回收实例 → 但同一宿主机仍被分配 → 循环

**根因：** GPU 内存修复进程卡死；EC2 健康检查未识别（DCGM 版本 bug）

**处理：**
1. 开 AWS Support Case（Sev-1）
2. 提供 Host Agent 日志 + DCGM exit code
3. EC2 团队确认故障宿主机并下线
4. 集群自动恢复

**预防：** 使用 Spare Instance（X+1 或 X+2 预留策略）

### HyperPod 已知监控盲区

| 盲区 | 描述 | 补充方案 |
|------|------|---------|
| EFA 故障 | `describe-cluster-node` 对 EFA 故障无感知 | 部署 EFA 健康检查脚本 |
| 内核内存碎片化 | HMA 不监控 | 自建 `/proc/buddyinfo` 监控 |
| NVMe/CSI 不兼容 | LIS CSI Driver 与 LVM 冲突 | 部署前确认 CSI 兼容性 |

---

## 关键经验（Lessons Learned）

1. **EC2 Status Check 不检测 GPU 故障** — 必须自行实现 GPU 监控
2. **Reboot ≠ 恢复 NVLink 故障** — 需要 EC2 lifecycle recycle 或 FM restart
3. **HBM row remap ≠ GPU 坏了** — 只有 `failure=Yes` 才满足 NVIDIA 退役标准
4. **同一物理机可能被重新分配** — Capacity Block 池中无 quarantine 机制
5. **FM restart 可恢复 Xid 145 隔离** — <1 分钟，无需换实例
6. **nvidia-bug-report 是 NVIDIA 介入的前提** — 务必在 terminate 前收集
7. **跨主机关联故障排除独立硬件问题** — 是判断软件/固件 bug 的关键证据
8. **温度异常（>60°C idle）= 硬件级故障信号** — 软件问题不会导致温度异常

---

## 监控建议（预防）

### 必须监控的 DCGM 指标

| 指标 | 告警条件 | 含义 |
|------|---------|------|
| `DCGM_FI_DEV_XID_ERRORS` | > 0 | 有 Xid 错误发生 |
| `DCGM_FI_DEV_ECC_DBE_VOL_TOTAL` | > 0 | 有 uncorrectable ECC 错误 |
| `DCGM_FI_DEV_ROW_REMAP_FAILURE` | = 1 | HBM spare row 耗尽，需 terminate |
| `DCGM_EXP_GPU_HEALTH_STATUS` | != healthy | GPU 健康异常 |
| `DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS` | 趋势上升 | HBM 持续退化 |
| `DCGM_FI_DEV_GPU_TEMP` | > 85°C | 温度异常（可能 GPU 卡死） |

### nvidia-smi 关键监控项

| 指标 | 告警条件 |
|------|---------|
| `sram_threshold_exceeded` | = Yes |
| `remapped_rows.failure` | = Yes |

### EKS Node Monitoring Agent (NMA) — 自动化 GPU 健康检测

AWS 原生方案，推荐启用：
- 自动检测 Xid 48/63/64/68/74/79/94/95/119/120 等错误
- 检测到后自动标记节点为 `NodeCondition` → 触发 auto-repair（节点替换或重启）
- 参考：https://docs.aws.amazon.com/eks/latest/userguide/node-health-nma.html

启用方法：
```yaml
# 在 EKS 集群配置中启用 node auto repair
aws eks update-cluster-config \
  --name <cluster> \
  --compute-config nodeAutoRepair=enabled
```

### NVIDIA NVSentinel — 开源 GPU 故障检测与自动修复（推荐）

适用于 self-managed EKS 集群，提供：
- **GPU Health Monitor**：通过 DCGM 持续监控 ECC 错误、温度、PCIe 故障
- **Fault Quarantine**：自动隔离故障节点，防止新 workload 调度上去
- **Preflight Check**：Pod 启动前注入 init container 验证 GPU 健康
- **Break-fix Workflow**：自动触发节点排空 → 替换 → 恢复

安装：
```bash
# 参考 https://github.com/NVIDIA/NVSentinel
helm install nvsentinel nvidia/nvsentinel -n gpu-health --create-namespace
```

### 推荐自动化（自建 DaemonSet — 当不使用 NVSentinel 时）

- 检测 dmesg 中 Xid 94/145 事件
- 自动收集 nvidia-bug-report
- 对 Xid 145（FM 隔离）：自动 restart fabricmanager + restart device-plugin
- 对 Xid 94 + FULLCHIP_RESET：自动 cordon → 收集日志 → 通知

---

## HyperPod/EKS 集群常见非 GPU 故障补充

> 以下问题非 GPU 硬件故障，但在大规模 GPU 集群中频繁出现，影响训练可用性。

### EFA 间歇性故障导致训练挂起

**症状：**
- 训练任务突然无响应
- 日志出现 `EFA_IO_COMP_STATUS_REMOTE_ERROR_UNKNOWN_PEER`（Error 14）
- NCCL watchdog 超时（默认 30 分钟后级联失败）

**排查：**
1. 确认是否是 Xid 31（应用层 MMU fault）→ 重启训练即可
2. 检查安全组自包含规则（**最高频原因**）
3. 如果 Xid 31 反复出现在同一节点 → 开 Case 请求 node replacement

**预防：**
```
# 安全组必须添加自包含出站规则
Source: 本安全组 ID
Protocol: All
Port: All
```

### 内核内存碎片化导致 EFA Endpoint 创建失败

**症状：**
- 集群运行 1 个月以上 后出现
- `fi_enable()` 返回 `ENOMEM`
- dmesg: `page allocation failure: order:7`

**根因：** 长时间运行 + SIGKILL 终止训练 → 内核无法回收大页内存映射 → 碎片化累积

**修复：** 重启受影响节点（清除内存碎片）

**预防：**
- 长期运行集群（>1 个月）定期滚动重启少量节点
- 避免 SIGKILL，优先使用 SIGTERM
- 监控 `/proc/buddyinfo` 中 order:7+ 可用块数量

### NCCL 通信问题排查

| 问题 | 可能原因 | 解决 |
|------|---------|------|
| NCCL Test 找不到 EFA | LD_LIBRARY_PATH 不正确 | 使用平台专用路径 |
| NCCL Test 挂起数十分钟 | NIC 故障 / EFA 拥塞 | 检查 NIC 状态 |
| all_reduce 性能低于预期 | EFA 未激活 | 确认 `NET/OFI Selected Provider is efa` |
| NCCL 使用 eth0 | 未排除管理网卡 | 设置 `NCCL_SOCKET_IFNAME=^docker,^eth0,lo,eth,veth` |

---

## 一键诊断收集脚本

```bash
#!/bin/bash
# GPU 故障诊断一键收集脚本
# 用法: sudo bash gpu-diag-collect.sh

OUTPUT_DIR="/tmp/gpu-diag-$(hostname)-$(date +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUTPUT_DIR"

echo "=== 开始收集 GPU 诊断信息 → $OUTPUT_DIR ==="

# GPU 状态
nvidia-smi > "$OUTPUT_DIR/nvidia-smi.txt" 2>&1
nvidia-smi -q > "$OUTPUT_DIR/nvidia-smi-q.txt" 2>&1
nvidia-smi nvlink --status > "$OUTPUT_DIR/nvlink-status.txt" 2>&1
nvidia-smi nvlink -e > "$OUTPUT_DIR/nvlink-errors.txt" 2>&1
nvidia-smi --query-remapped-rows=gpu_uuid,remapped_rows.correctable,remapped_rows.uncorrectable,remapped_rows.pending,remapped_rows.failure --format=csv > "$OUTPUT_DIR/remapped-rows.csv" 2>&1
nvidia-smi --query-gpu=gpu_uuid,index,name,serial,temperature.gpu,power.draw,ecc.errors.corrected.volatile.total,ecc.errors.uncorrected.volatile.total --format=csv > "$OUTPUT_DIR/gpu-health.csv" 2>&1

# 系统日志
dmesg | grep -i "nvrm\|xid\|nvidia\|nvlink\|reset\|bad.*register" > "$OUTPUT_DIR/dmesg-nvidia.log" 2>&1
dmesg > "$OUTPUT_DIR/dmesg-full.log" 2>&1

# Fabric Manager
journalctl -u nvidia-fabricmanager --since "48h ago" > "$OUTPUT_DIR/fm-journal-48h.log" 2>&1
systemctl status nvidia-fabricmanager > "$OUTPUT_DIR/fm-status.txt" 2>&1

# NVIDIA 完整诊断包
nvidia-bug-report.sh 2>&1
cp /tmp/nvidia-bug-report.log.gz "$OUTPUT_DIR/" 2>/dev/null

# DCGM 诊断（如可用）
which dcgmi >/dev/null 2>&1 && dcgmi diag -r 3 > "$OUTPUT_DIR/dcgmi-diag-r3.txt" 2>&1

# 元信息
echo "Hostname: $(hostname)" > "$OUTPUT_DIR/meta.txt"
echo "Date: $(date -u)" >> "$OUTPUT_DIR/meta.txt"
echo "Uptime: $(uptime)" >> "$OUTPUT_DIR/meta.txt"
echo "Kernel: $(uname -r)" >> "$OUTPUT_DIR/meta.txt"
cat /proc/driver/nvidia/version >> "$OUTPUT_DIR/meta.txt" 2>/dev/null

# 打包
tar -czf "${OUTPUT_DIR}.tar.gz" -C /tmp "$(basename $OUTPUT_DIR)"
echo ""
echo "=== 收集完成 ==="
echo "文件: ${OUTPUT_DIR}.tar.gz"
echo "请将此文件上传到 AWS Support Case"
```

---

## 参考链接

- [NVIDIA Xid Error Codes (EKS NMA)](https://docs.aws.amazon.com/eks/latest/userguide/node-health-nma.html#nvidia-xid-codes)
- [Troubleshoot Xid Errors (AWS repost)](https://www.repost.aws/knowledge-center/ec2-linux-troubleshoot-xid-errors)
- [NVIDIA Row Remapping 机制](https://docs.nvidia.com/deploy/a100-gpu-mem-error-mgmt/latest/row-remapping.html)
- [NVIDIA RMA 退役标准](https://docs.nvidia.com/deploy/a100-gpu-mem-error-mgmt/latest/rma-policy-thresholds-for-row-remapping.html)
- [NVIDIA Xid Catalog 分析](https://docs.nvidia.com/deploy/xid-errors/analyzing-xid-catalog.html)
- [NVIDIA NVSentinel (开源 GPU 故障自动修复)](https://github.com/NVIDIA/NVSentinel)
- [EKS Node Monitoring Agent (NMA)](https://docs.aws.amazon.com/eks/latest/userguide/node-health-nma.html)
- [EKS Node Auto-Repair 博客](https://aws.amazon.com/blogs/containers/amazon-eks-introduces-node-monitoring-and-auto-repair-capabilities/)
- [SageMaker HyperPod Health Monitoring](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-eks-resiliency-health-monitoring-agent.html)
- [SageMaker HyperPod Deep Health Checks](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-resiliency-slurm-deep-health-checks.html)
- [AWS GPU Telemetry 博客](https://aws.amazon.com/blogs/compute/capturing-gpu-telemetry-on-the-amazon-ec2-accelerated-computing-instances/)
- [EFA + NCCL 配置指南](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-start-nccl-dlami.html)
- [CB 到期监控方案](https://github.com/aws-samples/sample-capacity-reservation-notifier)
