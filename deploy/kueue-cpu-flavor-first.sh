#!/usr/bin/env bash
# =============================================================================
# Kueue ClusterQueue: 把 CPU flavor 排到 GPU flavor 前面 (CPU 任务优先落 CPU IG)
#
# 背景: 一个 workspace 算力池含多个 instance group (g6 GPU + m5 CPU)。
# Kueue admit workload 时按 ClusterQueue.spec.resourceGroups[].flavors[] 顺序匹配 flavor。
# task-governance 默认生成的顺序 GPU flavor 在前 → CPU 任务 (开发机, 无 GPU 请求) 也
# 先匹配上 GPU flavor → 注入 GPU nodeLabel → 落 GPU 节点 (浪费)。
#
# 本脚本把 GPU quota=0 的 flavor (CPU flavor) 排到前面:
#   - CPU 任务 → 先匹配 CPU flavor → 落 CPU 节点; CPU 满了 fallback GPU (软优先)
#   - GPU 任务 (请求 nvidia.com/gpu) → CPU flavor gpu quota=0, Kueue 自动跳过 → 落 GPU (无害)
#
# 幂等: 已是 CPU-first 则跳过。可回滚 (自动备份)。只影响 patch 之后新建的 workload,
# 不重调度已运行的 pod (patch ClusterQueue 不产生任何 Pod)。
#
# ⚠️ ClusterQueue 是 SageMaker task-governance 托管资源 (sagemaker-managed-queue label),
#    patch 可能被 reconcile 覆盖 (TODO #32 观察中)。若被覆盖, 需做成周期性
#    重排 (CronJob) 或改走方案 C (平台渲染 CR 写 affinity.required)。
#
# 用法:
#   AWS_PROFILE=hypd-029 AWS_REGION=us-west-2 \
#     CQ=hyperpod-ns-demo-clusterqueue ./kueue-cpu-flavor-first.sh
#   # dry-run 只看不改:
#   DRY_RUN=1 CQ=hyperpod-ns-demo-clusterqueue ./kueue-cpu-flavor-first.sh
#   # 所有 ws 批量 (自动发现所有 sagemaker-managed ClusterQueue):
#   ALL=1 ./kueue-cpu-flavor-first.sh
#
# env: CQ (单个 ClusterQueue 名) | ALL=1 (批量所有托管 CQ) | DRY_RUN=1 (只看)
# =============================================================================
set -euo pipefail

DRY_RUN="${DRY_RUN:-0}"
ALL="${ALL:-0}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERR]${NC} $*"; }

# 对单个 ClusterQueue 重排 flavor (CPU flavor 提前)
reorder_cq() {
  local cq="$1"
  local rv backup tmp_patch
  rv=$(kubectl get clusterqueue "$cq" -o jsonpath='{.metadata.resourceVersion}' 2>/dev/null) || {
    err "ClusterQueue '$cq' 不存在"; return 1; }
  backup="/tmp/${cq}-backup-${rv}.yaml"
  tmp_patch="/tmp/${cq}-cpufirst.json"

  kubectl get clusterqueue "$cq" -o yaml > "$backup"
  log "[$cq] 备份 → $backup"

  # 生成 patch: flavors 按 "GPU quota 为 0 的排前面" 稳定重排 (CPU flavor 优先, 组内保原序)
  local rc=0
  kubectl get clusterqueue "$cq" -o json | python3 -c "
import json, sys
d = json.load(sys.stdin)
rg = d['spec']['resourceGroups'][0]

def gpu_quota(f):
    for r in f.get('resources', []):
        if r['name'] == 'nvidia.com/gpu':
            try:
                return float(str(r.get('nominalQuota', '0')).rstrip('Gi'))
            except ValueError:
                return 0.0
    return 0.0

flavors = rg['flavors']
# False(0)=CPU 排前, True(1)=GPU 排后; sorted 稳定保组内原序
reordered = sorted(flavors, key=lambda f: gpu_quota(f) > 0)
if [f['name'] for f in reordered] == [f['name'] for f in flavors]:
    sys.exit(3)  # 已是 CPU-first, 无需改
patch = {'spec': {'resourceGroups': [
    {'coveredResources': rg['coveredResources'], 'flavors': reordered}
]}}
json.dump(patch, open('$tmp_patch', 'w'))
sys.stderr.write('NEW_ORDER ' + ' '.join(f['name'] for f in reordered) + '\n')
" 2>/tmp/.cpuflavor.msg || rc=$?

  if [ "$rc" = "3" ]; then
    ok "[$cq] 已是 CPU-first, 跳过"
    return 0
  elif [ "$rc" != "0" ]; then
    err "[$cq] 生成 patch 失败"; cat /tmp/.cpuflavor.msg; return 1
  fi
  cat /tmp/.cpuflavor.msg

  if [ "$DRY_RUN" = "1" ]; then
    warn "[$cq] dry-run, 不应用。patch 文件: $tmp_patch"
    return 0
  fi

  kubectl patch clusterqueue "$cq" --type merge --patch-file "$tmp_patch"
  ok "[$cq] flavor 重排完成: $(kubectl get clusterqueue "$cq" -o jsonpath='{range .spec.resourceGroups[0].flavors[*]}{.name}{" "}{end}')"
  log "[$cq] 回滚: kubectl apply -f $backup"
}

# ---------- main ----------
log "Account=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo '?') Region=${AWS_REGION:-?}"

if [ "$ALL" = "1" ]; then
  log "批量模式: 发现所有 sagemaker-managed ClusterQueue..."
  mapfile -t cqs < <(kubectl get clusterqueue \
    -l sagemaker.amazonaws.com/sagemaker-managed-queue=true \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null)
  if [ "${#cqs[@]}" -eq 0 ]; then
    warn "没发现 sagemaker-managed ClusterQueue (检查 label / 集群连接)"; exit 0
  fi
  log "共 ${#cqs[@]} 个: ${cqs[*]}"
  for cq in "${cqs[@]}"; do
    [ -n "$cq" ] && reorder_cq "$cq" || true
  done
else
  CQ="${CQ:?必须设 CQ (ClusterQueue 名) 或 ALL=1 批量}"
  reorder_cq "$CQ"
fi

echo
ok "完成 (dry-run=${DRY_RUN})"
warn "提醒: 托管 ClusterQueue 的 patch 可能被 task-governance 覆盖 (待观察)。"
warn "      若需持久, 考虑做成定时重排或改走方案 C (CR affinity.required)。"
