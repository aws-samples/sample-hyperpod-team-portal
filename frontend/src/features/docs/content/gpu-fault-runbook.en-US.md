# GPU Node Fault Diagnosis Runbook
## Applies to: Capacity Block / Self-Managed EKS / SageMaker HyperPod

**Version:** 1.0 | **Updated:** 2026-07-06

---

## When to Use This Runbook

Nodes in the GPU cluster show any of the following symptoms:
- Node NotReady / Pod CrashLoopBackOff
- `nvidia-smi` shows ERR! or some GPUs are unavailable
- Xid errors (31/38/94/137/145)
- GPU requires reset / FULLCHIP_RESET
- Multiple GPUs isolated by Fabric Manager (FM)
- The problem comes back after deleting/rebooting the node
- The same physical GPU UUID keeps getting assigned back and keeps reporting errors

---

## Step 1: Collect Basic Information

| Item | Command/Source |
|--------|-----------|
| Instance ID | `kubectl get node <node> -o jsonpath='{.spec.providerID}'` |
| Launch time | `kubectl get node <node> -o jsonpath='{.metadata.creationTimestamp}'` |
| GPU model/count | `nvidia-smi --query-gpu=name,count --format=csv` |
| Symptom description | The exact error type: which Xid number? GPU requires reset? ERR!? 7/8 isolated? |
| Scope of impact | How many GPUs are affected? The whole node or a single GPU? |
| Recurrence frequency | How long after each reboot does it come back? Does it persist across reboots? |

---

## Step 2: GPU Status Logs (⚠️ Collect While in the Faulty State, Before Terminating)

> **Key principle: collect first, then act. The data is lost after Terminate.**

SSH into the faulty node and run:

```bash
# Overall GPU status
nvidia-smi

# Detailed GPU info (ECC, temperature, power, remapped rows)
nvidia-smi -q

# NVLink status
nvidia-smi nvlink --status

# NVLink error counters
nvidia-smi nvlink -e

# Remapped rows (to judge HBM health)
nvidia-smi --query-remapped-rows=gpu_uuid,remapped_rows.correctable,remapped_rows.uncorrectable,remapped_rows.pending,remapped_rows.failure --format=csv

# GPU UUID list (for tracking the physical hardware later)
nvidia-smi --query-gpu=gpu_uuid,index,name,serial,temperature.gpu --format=csv

# Full NVIDIA diagnostic bundle (the key file to submit to AWS/NVIDIA)
sudo nvidia-bug-report.sh
```

---

## Step 3: System Logs

```bash
# nvidia/Xid/NVLink-related entries in dmesg
dmesg | grep -i "nvrm\|xid\|nvidia\|nvlink\|reset\|bad.*register" > dmesg-nvidia.log

# Full dmesg
dmesg > dmesg-full.log

# Fabric Manager logs (the key component for NVSwitch/NVLink multi-GPU communication)
journalctl -u nvidia-fabricmanager --since "48h ago" > fm-journal-48h.log
systemctl status nvidia-fabricmanager > fm-status.txt
```

---

## Step 4: DCGM Diagnostics (If Installed)

```bash
# Level 3 full diagnostics (takes about 10-15 minutes)
dcgmi diag -r 3

# Or check the key metrics via Prometheus/DCGM exporter:
# DCGM_FI_DEV_XID_ERRORS > 0
# DCGM_FI_DEV_ECC_DBE_VOL_TOTAL > 0
# DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS > 0
# DCGM_FI_DEV_ROW_REMAP_FAILURE = 1
# DCGM_EXP_GPU_HEALTH_STATUS != healthy
```

---

## Step 5: Quick Fault Classification

Based on the information collected, use the table below to determine the fault type:

| Fault type | Key characteristics | Impact | Recovery |
|---------|---------|------|---------|
| **A: GPU fallen off the bus** | nvidia-smi shows ERR!; dmesg has `0xbad…` poison values; FULLCHIP_RESET; abnormally high temperature | A single GPU is completely unusable, and the whole node is written off | **EC2 terminate** (no software recovery) |
| **B: NVLink Xid 145 FM isolation** | 7/8 GPUs isolated; ECC counters all zero; FM journal has Xid 145/137; normal temperature | 7 GPUs cannot be allocated, 1 GPU works normally | **Restart Fabric Manager** (recovers in <1 minute) |
| **C: HBM wear (normal)** | uncorrectable_remapped_rows > 0; failure=No | The GPU can still be used normally | **Keep using it, keep monitoring** |
| **D: HBM exhausted** | remapping_failure=Yes | The GPU must be retired | **EC2 terminate** (automatic degrade) |
| **E: Single-GPU Xid 94 (typical ECC)** | A single GPU reports Xid 94; ECC counters are growing; no cascade | A single GPU is unusable | **EC2 stop/start or terminate** |
| **F: Xid 38 (driver channel error)** | A single GPU reports Xid 38; the node silently degrades to 7/8 | One GPU fewer | **EC2 terminate + relaunch** |
| **G: Correlated cross-host fault** | Multiple independent hosts trigger the same error within seconds; identical error signature | Multiple nodes affected at once | **Restart FM (temporary); NVIDIA involvement required** |
| **X: Unknown fault** | Does not match any of the patterns above | Needs investigation | **Keep the instance, collect all data, open a Case and escalate** |

---

## Step 6: Recovery Actions

### Fault A: GPU Fallen off the Bus (ERR! / FULLCHIP_RESET)

```
1. Confirm that all diagnostic logs have been collected
2. Open an AWS Support Case (severity: critical)
3. Wait for Support to confirm the physical host has been isolated
4. Terminate the instance → Karpenter/ASG automatically launches a replacement
5. Verify that the new node has 8/8 healthy GPUs
```

### Fault B: NVLink Xid 145 / Multiple GPUs Isolated

```bash
# Restart Fabric Manager (no instance reboot needed)
sudo systemctl restart nvidia-fabricmanager

# Restart the device-plugin Pod (re-enumerates the GPUs)
kubectl -n gpu-operator delete pod <nvidia-device-plugin-pod-on-this-node>

# Uncordon the node
kubectl uncordon <node>

# Verify: expect 8/8 GPUs to be back within ~1 minute
kubectl get node <node> -o jsonpath='{.status.allocatable.nvidia\.com/gpu}'
```

### Fault C: HBM Wear (failure=No)

```
No immediate action needed. The GPU is still safe to use.
Keep monitoring the following metrics:
- DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS → trend
- DCGM_FI_DEV_ROW_REMAP_FAILURE → once it becomes Yes, terminate is required

To reset the row remap state: an EC2 stop/start or terminate+relaunch triggers it.
```

### Fault D: HBM Exhausted (failure=Yes)

```
1. Terminate the instance
2. EC2 health checks automatically degrade that host, and it is never assigned to any customer again
3. Karpenter/ASG automatically launches a replacement on new hardware
4. No need to request isolation manually
```

### Faults E/F: Single-GPU Xid 94 / Xid 38

```
1. EC2 terminate+relaunch (or stop/start)
2. After recovery, check remapped_rows: if failure=No, the GPU is safe to use
3. If the same UUID keeps having problems: record the UUID and open a Case to follow up
```

### Fault G: Correlated Cross-Host Fault

```
1. Collect the full diagnostic bundle on every affected node
2. Record exact timestamps + all instance IDs + error signatures
3. On each node, run: sudo systemctl restart nvidia-fabricmanager (temporary recovery)
4. Open a Case immediately and flag it as a fleet-level systemic issue
5. Prove the correlation: the same error code/subcode/timing appears on different physical hosts/racks
```

### Fault X: Handling Unknown Faults

```
1. Do not guess the root cause: treat it as a new issue
2. Keep the instance: do not terminate or reboot it until diagnosis is complete
3. Collect all data (use the script in 'One-Click Diagnostic Collection Script' below)
4. Try non-destructive recovery (in order):
   a) nvidia-smi -r (GPU reset)
   b) systemctl restart nvidia-fabricmanager
   c) consider a reboot only as a last resort
   → record the result of each step
5. Check against the classification table in Step 5 to see whether it fits a known pattern
6. If it still cannot be classified → open a Case with all logs and label it "unknown fault type"
7. Notify your TAM to escalate
```

---

## Step 7: Opening a Case and Escalating

### Provide the Following When Opening a Case

```
Subject: GPU fault — [brief symptom] — [instance type] — [region]
Severity: Critical (if it blocks training)

The body should include:
- Instance ID
- GPU UUID (of the faulty GPU)
- Symptom description + timeline
- Fault type assessment (A-G/X)
- Recovery actions attempted and their results
- Diagnostic files uploaded to the Case
```

### When TAM Escalation Is Needed

- The same Capacity Block keeps having faults (a suspected physical hardware defect)
- The fault type is G (correlated cross-host) or X (unknown)
- The Support response takes longer than expected
- The fault affects training progress or a product release milestone

---

## Step 8: Follow-Up

| Check | How to verify |
|--------|---------|
| All GPUs on the new node are healthy | `nvidia-smi` — 8/8 GPUs visible, no ERR! |
| All NVLinks active | `nvidia-smi nvlink --status` — every link has bandwidth |
| Not assigned the old faulty hardware | Compare GPU UUIDs — they should differ from the faulty machine |
| Remapped rows are clean | `--query-remapped-rows` — confirm the new node has no residual damage |
| Pods schedule normally | `kubectl get pods -o wide` — GPU Pods are running on the new node |

---

## SageMaker HyperPod Supplement

> The following applies only to SageMaker HyperPod managed clusters. Skip it for self-managed EKS.

### HyperPod's Automatic Recovery

HyperPod has a built-in **Health Monitoring Agent (HMA)** that provides:
- Continuous GPU health monitoring (DCGM level)
- NVLink / EFA connectivity checks
- Automatic marking as unhealthy → automatic draining → automatic node replacement

**When HMA handles it automatically:**
- No manual intervention needed
- Typical recovery time: 5-15 minutes
- Verify in: CloudWatch Logs `/aws/sagemaker/Clusters/<cluster-name>/HealthMonitoringAgent`

### Faults HMA Fails to Detect

In the following cases, HMA may not trigger a replacement automatically:
- Xid 145 FM isolation (multiple GPUs, while the instance is still "reachable")
- Gradual HBM wear (below the immediate-failure threshold)
- New error patterns (not covered by HMA's detection rules)

**In these cases:** diagnose and recover manually following Steps 2-6 above.

### HyperPod Deep Health Check (Proactive Detection)

Run it proactively before starting large-scale training:

```bash
# Trigger a Deep Health Check
aws sagemaker create-cluster-node-group-action \
  --cluster-name <cluster> \
  --node-group <group> \
  --action-type DeepHealthCheck \
  --target-instances <instance-id>
```

| Check type | What it covers |
|---------|------|
| InstanceHealth | GPU/PCI validation + DCGM diagnostics + EFA loopback |
| InstanceConnectivity | Cross-node NCCL communication performance validation |

**Interpreting the results:**
- PASS → the hardware is healthy; the problem is in the workload/software layer
- FAIL + a specific component → pinpoints the fault (GPU N / NVLink link M / EFA port X)

### Manually Replacing Nodes in HyperPod

**Slurm clusters:**
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

**EKS-based HyperPod:**
- Cordon + drain the node
- Delete the corresponding MachineDeployment/NodeClaim
- The HyperPod controller automatically provisions a replacement

### Self-Healing Recommendations for HyperPod Lifecycle Scripts

Add to your lifecycle scripts:

```bash
# on-node-start: verify GPU health before joining the pool
nvidia-smi -q | grep -i "remapping failure" | grep -i "yes" && exit 1

# on-fault-detected: collect diagnostics automatically before replacement
/opt/gpu-diag-collect.sh
aws s3 cp /tmp/gpu-diag-*.tar.gz s3://<your-bucket>/diagnostics/
```

### HyperPod-Specific Fault: GPU Boot Loop

**Symptoms:**
- LCC (Lifecycle Configuration) repeatedly fails on multiple instances
- DCGM exit code 226 appears in the Host Agent logs
- HMA detects the fault → reclaims the instance → but the same host is still assigned → loop

**Root cause:** the GPU memory repair process hangs; EC2 health checks do not detect it (a DCGM version bug)

**Resolution:**
1. Open an AWS Support Case (Sev-1)
2. Provide the Host Agent logs + DCGM exit code
3. The EC2 team confirms the faulty host and takes it offline
4. The cluster recovers automatically

**Prevention:** use Spare Instances (an X+1 or X+2 reservation strategy)

### Known HyperPod Monitoring Blind Spots

| Blind spot | Description | Mitigation |
|------|------|---------|
| EFA faults | `describe-cluster-node` is unaware of EFA faults | Deploy an EFA health check script |
| Kernel memory fragmentation | Not monitored by HMA | Build your own `/proc/buddyinfo` monitoring |
| NVMe/CSI incompatibility | The LIS CSI Driver conflicts with LVM | Confirm CSI compatibility before deployment |

---

## Lessons Learned

1. **EC2 Status Checks do not detect GPU faults** — you must implement GPU monitoring yourself
2. **A reboot does not fix NVLink faults** — you need an EC2 lifecycle recycle or an FM restart
3. **HBM row remap ≠ a broken GPU** — only `failure=Yes` meets NVIDIA's retirement criteria
4. **The same physical host may be reassigned** — there is no quarantine mechanism in the Capacity Block pool
5. **An FM restart can recover Xid 145 isolation** — in <1 minute, without replacing the instance
6. **nvidia-bug-report is a prerequisite for NVIDIA involvement** — always collect it before terminating
7. **Correlated cross-host faults rule out independent hardware problems** — this is key evidence for identifying a software/firmware bug
8. **Abnormal temperature (>60°C idle) = a hardware-level fault signal** — software problems do not cause abnormal temperatures

---

## Monitoring Recommendations (Prevention)

### DCGM Metrics You Must Monitor

| Metric | Alert condition | Meaning |
|------|---------|------|
| `DCGM_FI_DEV_XID_ERRORS` | > 0 | An Xid error has occurred |
| `DCGM_FI_DEV_ECC_DBE_VOL_TOTAL` | > 0 | There are uncorrectable ECC errors |
| `DCGM_FI_DEV_ROW_REMAP_FAILURE` | = 1 | HBM spare rows are exhausted; terminate is required |
| `DCGM_EXP_GPU_HEALTH_STATUS` | != healthy | GPU health is abnormal |
| `DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS` | Rising trend | HBM is steadily degrading |
| `DCGM_FI_DEV_GPU_TEMP` | > 85°C | Abnormal temperature (the GPU may be hung) |

### Key nvidia-smi Monitoring Items

| Metric | Alert condition |
|------|---------|
| `sram_threshold_exceeded` | = Yes |
| `remapped_rows.failure` | = Yes |

### EKS Node Monitoring Agent (NMA) — Automated GPU Health Detection

The AWS-native option, recommended:
- Automatically detects errors such as Xid 48/63/64/68/74/79/94/95/119/120
- On detection, automatically marks the node with a `NodeCondition` → triggers auto-repair (node replacement or reboot)
- Reference: https://docs.aws.amazon.com/eks/latest/userguide/node-health-nma.html

How to enable it:
```yaml
# Enable node auto repair in the EKS cluster configuration
aws eks update-cluster-config \
  --name <cluster> \
  --compute-config nodeAutoRepair=enabled
```

### NVIDIA NVSentinel — Open-Source GPU Fault Detection and Auto-Remediation (Recommended)

For self-managed EKS clusters, it provides:
- **GPU Health Monitor**: continuously monitors ECC errors, temperature, and PCIe faults via DCGM
- **Fault Quarantine**: automatically isolates faulty nodes so new workloads are not scheduled onto them
- **Preflight Check**: injects an init container before a Pod starts to verify GPU health
- **Break-fix Workflow**: automatically triggers node draining → replacement → recovery

Installation:
```bash
# See https://github.com/NVIDIA/NVSentinel
helm install nvsentinel nvidia/nvsentinel -n gpu-health --create-namespace
```

### Recommended Automation (a Self-Built DaemonSet, When Not Using NVSentinel)

- Detect Xid 94/145 events in dmesg
- Automatically collect nvidia-bug-report
- For Xid 145 (FM isolation): automatically restart fabricmanager + restart device-plugin
- For Xid 94 + FULLCHIP_RESET: automatically cordon → collect logs → notify

---

## Common Non-GPU Faults in HyperPod/EKS Clusters

> The following problems are not GPU hardware faults, but they occur frequently in large GPU clusters and affect training availability.

### Intermittent EFA Faults Causing Training Hangs

**Symptoms:**
- The training job suddenly becomes unresponsive
- `EFA_IO_COMP_STATUS_REMOTE_ERROR_UNKNOWN_PEER` (Error 14) appears in the logs
- NCCL watchdog timeout (cascading failure after 30 minutes by default)

**Troubleshooting:**
1. Check whether it is Xid 31 (an application-level MMU fault) → just restart the training
2. Check the security group's self-referencing rule (**the most frequent cause**)
3. If Xid 31 keeps appearing on the same node → open a Case to request a node replacement

**Prevention:**
```
# The security group must have a self-referencing outbound rule
Source: this security group's ID
Protocol: All
Port: All
```

### Kernel Memory Fragmentation Causing EFA Endpoint Creation Failures

**Symptoms:**
- Appears after the cluster has been running for more than a month
- `fi_enable()` returns `ENOMEM`
- dmesg: `page allocation failure: order:7`

**Root cause:** long uptime + training terminated with SIGKILL → the kernel cannot reclaim large-page memory mappings → fragmentation accumulates

**Fix:** reboot the affected nodes (clears the memory fragmentation)

**Prevention:**
- For long-running clusters (>1 month), periodically do rolling reboots of a few nodes
- Avoid SIGKILL; prefer SIGTERM
- Monitor the number of available order:7+ blocks in `/proc/buddyinfo`

### Troubleshooting NCCL Communication Issues

| Problem | Possible cause | Solution |
|------|---------|------|
| NCCL Test cannot find EFA | LD_LIBRARY_PATH is incorrect | Use the platform-specific path |
| NCCL Test hangs for tens of minutes | NIC fault / EFA congestion | Check the NIC status |
| all_reduce performance is lower than expected | EFA is not active | Confirm `NET/OFI Selected Provider is efa` |
| NCCL uses eth0 | The management NIC is not excluded | Set `NCCL_SOCKET_IFNAME=^docker,^eth0,lo,eth,veth` |

---

## One-Click Diagnostic Collection Script

```bash
#!/bin/bash
# One-click GPU fault diagnostic collection script
# Usage: sudo bash gpu-diag-collect.sh

OUTPUT_DIR="/tmp/gpu-diag-$(hostname)-$(date +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUTPUT_DIR"

echo "=== Collecting GPU diagnostic information → $OUTPUT_DIR ==="

# GPU status
nvidia-smi > "$OUTPUT_DIR/nvidia-smi.txt" 2>&1
nvidia-smi -q > "$OUTPUT_DIR/nvidia-smi-q.txt" 2>&1
nvidia-smi nvlink --status > "$OUTPUT_DIR/nvlink-status.txt" 2>&1
nvidia-smi nvlink -e > "$OUTPUT_DIR/nvlink-errors.txt" 2>&1
nvidia-smi --query-remapped-rows=gpu_uuid,remapped_rows.correctable,remapped_rows.uncorrectable,remapped_rows.pending,remapped_rows.failure --format=csv > "$OUTPUT_DIR/remapped-rows.csv" 2>&1
nvidia-smi --query-gpu=gpu_uuid,index,name,serial,temperature.gpu,power.draw,ecc.errors.corrected.volatile.total,ecc.errors.uncorrected.volatile.total --format=csv > "$OUTPUT_DIR/gpu-health.csv" 2>&1

# System logs
dmesg | grep -i "nvrm\|xid\|nvidia\|nvlink\|reset\|bad.*register" > "$OUTPUT_DIR/dmesg-nvidia.log" 2>&1
dmesg > "$OUTPUT_DIR/dmesg-full.log" 2>&1

# Fabric Manager
journalctl -u nvidia-fabricmanager --since "48h ago" > "$OUTPUT_DIR/fm-journal-48h.log" 2>&1
systemctl status nvidia-fabricmanager > "$OUTPUT_DIR/fm-status.txt" 2>&1

# Full NVIDIA diagnostic bundle
nvidia-bug-report.sh 2>&1
cp /tmp/nvidia-bug-report.log.gz "$OUTPUT_DIR/" 2>/dev/null

# DCGM diagnostics (if available)
which dcgmi >/dev/null 2>&1 && dcgmi diag -r 3 > "$OUTPUT_DIR/dcgmi-diag-r3.txt" 2>&1

# Metadata
echo "Hostname: $(hostname)" > "$OUTPUT_DIR/meta.txt"
echo "Date: $(date -u)" >> "$OUTPUT_DIR/meta.txt"
echo "Uptime: $(uptime)" >> "$OUTPUT_DIR/meta.txt"
echo "Kernel: $(uname -r)" >> "$OUTPUT_DIR/meta.txt"
cat /proc/driver/nvidia/version >> "$OUTPUT_DIR/meta.txt" 2>/dev/null

# Package
tar -czf "${OUTPUT_DIR}.tar.gz" -C /tmp "$(basename $OUTPUT_DIR)"
echo ""
echo "=== Collection complete ==="
echo "File: ${OUTPUT_DIR}.tar.gz"
echo "Upload this file to your AWS Support Case"
```

---

## References

- [NVIDIA Xid Error Codes (EKS NMA)](https://docs.aws.amazon.com/eks/latest/userguide/node-health-nma.html#nvidia-xid-codes)
- [Troubleshoot Xid Errors (AWS repost)](https://www.repost.aws/knowledge-center/ec2-linux-troubleshoot-xid-errors)
- [NVIDIA Row Remapping Mechanism](https://docs.nvidia.com/deploy/a100-gpu-mem-error-mgmt/latest/row-remapping.html)
- [NVIDIA RMA Retirement Criteria](https://docs.nvidia.com/deploy/a100-gpu-mem-error-mgmt/latest/rma-policy-thresholds-for-row-remapping.html)
- [NVIDIA Xid Catalog Analysis](https://docs.nvidia.com/deploy/xid-errors/analyzing-xid-catalog.html)
- [NVIDIA NVSentinel (Open-Source GPU Fault Auto-Remediation)](https://github.com/NVIDIA/NVSentinel)
- [EKS Node Monitoring Agent (NMA)](https://docs.aws.amazon.com/eks/latest/userguide/node-health-nma.html)
- [EKS Node Auto-Repair Blog Post](https://aws.amazon.com/blogs/containers/amazon-eks-introduces-node-monitoring-and-auto-repair-capabilities/)
- [SageMaker HyperPod Health Monitoring](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-eks-resiliency-health-monitoring-agent.html)
- [SageMaker HyperPod Deep Health Checks](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-resiliency-slurm-deep-health-checks.html)
- [AWS GPU Telemetry Blog Post](https://aws.amazon.com/blogs/compute/capturing-gpu-telemetry-on-the-amazon-ec2-accelerated-computing-instances/)
- [EFA + NCCL Configuration Guide](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-start-nccl-dlami.html)
- [Capacity Block (CB) Expiration Monitoring Solution](https://github.com/aws-samples/sample-capacity-reservation-notifier)
