#!/usr/bin/env bash
#
# 在 FSx for Lustre 根下初始化多租户子目录 (team-a ~ team-d).
#   每个 team 目录:
#     - chgrp 到各自 group id (team-a=5001 ... team-d=5004)
#     - chmod 2770 (rwxrws---, setgid: 目录里新建文件/子目录自动继承该 gid)
#     - 写文件时 umask 002 + 显式 chmod 664: 文件 rw-rw-r--, 同组成员可写
#       (否则默认 umask 022 → 644 组只读, 用户在开发机编辑会 EACCES/read only)
#     - 父目录放 hello-<team>.txt; 随机 2-3 个子目录各放 sample-<sub>.txt
#
# 复用现成的 fsx-admin pod (不自建临时 pod) —— pod 已挂 FSx 根, 直接 exec 进去建目录。
# fsx-admin pod 由 deploy/k8s/fsx-admin.yaml 部署 (见 deployment-guideline.md §4.3),
# 后端也按同样的 ns/label 找它列子目录。
#
# 前提: fsx-admin pod 已 Running (kubectl get pods -n hyperpod-platform-system -l app=fsx-admin)。
#
# 用法:
#   ./fsx-init-team-dirs.sh                          # 用 current-context
#   KUBE_CONTEXT=hp-fsx-demo ./fsx-init-team-dirs.sh # 指定集群 context
# 可选:
#   NAMESPACE / LABEL / CONTAINER 覆盖 fsx-admin pod 定位 (默认与后端 config 一致)
#
set -euo pipefail

# ===== 可配置: team -> gid 映射 (沿用平台约定, 按需改) =====
# 注意: gid 必须 >= 1001 (1000 给 S3, 0/1 给 root/system)
declare -A TEAM_GID=(
  [team-a]=5001
  [team-b]=5002
  [team-c]=5003
  [team-d]=5004
)
DIR_MODE=2770   # rwxrws--- + setgid: 子目录新文件继承目录 gid

# ===== fsx-admin pod 定位 (默认与后端 config.py 一致) =====
NAMESPACE="${NAMESPACE:-hyperpod-platform-system}"
LABEL="${LABEL:-app=fsx-admin}"
CONTAINER="${CONTAINER:-sh}"
# kubectl context: 不设则用 current-context (跨集群时设成业务集群名)
KCTX=()
[ -n "${KUBE_CONTEXT:-}" ] && KCTX=(--context "$KUBE_CONTEXT")

echo ">> 1. 定位 fsx-admin pod (ns=$NAMESPACE label=$LABEL)"
POD=$(kubectl "${KCTX[@]}" -n "$NAMESPACE" get pods -l "$LABEL" \
  --field-selector=status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
if [ -z "$POD" ]; then
  echo "❌ 没找到 Running 的 fsx-admin pod (ns=$NAMESPACE label=$LABEL)" >&2
  echo "   先部署: 见 deployment-guideline.md §4.3 (deploy/k8s/fsx-admin.yaml)" >&2
  exit 1
fi
echo "   pod=$POD"

# 确认 pod 能看到 FSx 根
if ! kubectl "${KCTX[@]}" -n "$NAMESPACE" exec "$POD" -c "$CONTAINER" -- ls /fsx >/dev/null 2>&1; then
  echo "❌ pod 内 /fsx 不可访问 (FSx 没挂上?)" >&2
  exit 1
fi

echo ">> 2. 建 team 父目录 + 随机 2-3 个子目录 + 设 gid/mode + 写测试文件"
SUBDIR_POOL=(datasets models notebooks experiments checkpoints scratch)
for team in "${!TEAM_GID[@]}"; do
  gid="${TEAM_GID[$team]}"
  # 随机抽 2 或 3 个子目录名 (shuf 打乱取前 N)
  n=$(( RANDOM % 2 + 2 ))
  subdirs=$(printf '%s\n' "${SUBDIR_POOL[@]}" | shuf | head -n "$n" | tr '\n' ' ')
  kubectl "${KCTX[@]}" -n "$NAMESPACE" exec "$POD" -c "$CONTAINER" -- sh -c "
    set -e
    # ⭐ umask 002: 让本 shell 里新建文件默认 664 (rw-rw-r--), 目录 775 → 配合下面
    # 显式 chmod, 保证同组成员可写。默认 umask 022 会建出 644 (组只读), 用户
    # 在开发机 (同 gid, 非 owner) 编辑已有文件会 EACCES / 'read only'。
    umask 002
    d=/fsx/${team}
    mkdir -p \"\$d\"
    chgrp ${gid} \"\$d\"
    chmod ${DIR_MODE} \"\$d\"
    # 父目录测试文件 (显式 664: 组可写, 双保险不靠 umask)
    echo 'hello from ${team} (gid=${gid})' > \"\$d/hello-${team}.txt\"
    chgrp ${gid} \"\$d/hello-${team}.txt\"
    chmod 664 \"\$d/hello-${team}.txt\"
    # 随机子目录 (setgid 父目录 → 子目录及其文件自动继承 gid)
    for sub in ${subdirs}; do
      sd=\"\$d/\$sub\"
      mkdir -p \"\$sd\"
      chgrp ${gid} \"\$sd\"
      chmod ${DIR_MODE} \"\$sd\"
      echo \"sample data for ${team}/\$sub\" > \"\$sd/sample-\$sub.txt\"
      chgrp ${gid} \"\$sd/sample-\$sub.txt\"
      chmod 664 \"\$sd/sample-\$sub.txt\"
    done
    echo \"  [OK] ${team} -> gid=${gid}, subdirs: ${subdirs}\"
  "
done

echo ">> 3. 验证 /fsx 结果 (根下 4 个 drwxrws--- + 各 team 下的子目录/文件)"
kubectl "${KCTX[@]}" -n "$NAMESPACE" exec "$POD" -c "$CONTAINER" -- ls -ln /fsx/
echo "--- 各 team 子目录 ---"
kubectl "${KCTX[@]}" -n "$NAMESPACE" exec "$POD" -c "$CONTAINER" -- \
  sh -c 'for t in /fsx/*/; do echo "[$t]"; ls -ln "$t"; done'

echo ">> 完成 (复用现成 fsx-admin pod, 无临时资源需清理)。"
