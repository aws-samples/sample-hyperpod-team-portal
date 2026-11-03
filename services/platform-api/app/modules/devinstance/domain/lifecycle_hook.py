"""Workspace Pod postStart 生命周期脚本 (官方约束 <=1KB).

三个目的:
    1. EBS 空卷挂到 /home/sagemaker-user 会遮蔽镜像里的 seed 文件;
       第一次启动时从 /etc/skel + 镜像 /opt/.../workspace/skel 拷出,
       .bashrc / .profile / vscode-server 才能持久到 EBS.
    2. 幂等: 只有目标文件不存在才拷 (`cp -rn`), 不覆盖用户修改.
    3. 把 pod 的 supplementalGroups 同步进 /etc/group 并加 sagemaker-user 成员.
       原因: FSx 目录靠组 (mode 2770) 授权; supplementalGroups 由容器 runtime
       施加给容器 init 进程 (code-editor/jupyter 继承 → 能进 FSx), 但不写进
       /etc/group. directSSH 的 sshd (无 UsePAM) 登录走 initgroups() 只从
       /etc/passwd+/etc/group 推导 → SSH 会话丢掉这些组 → cd /fsx/team-* 被拒.
       这是 K8s 通用行为 (KEP-3619 / supplementalGroups 不入 /etc/group), directSSH
       上游无官方开关, 故 postStart 把 `id -G` 的附加组补进 /etc/group 修正.

调用方式 (Stop→Start 每次都跑):
    spec.lifecycle.postStart.exec.command = SEED_COMMAND
"""

from __future__ import annotations

# bash 脚本片段 · 单引号避免 shell 转义
# GRP_SYNC: 遍历容器全部组 (id -G, 含 runAsGroup 主组 + supplementalGroups);
# 组不在 /etc/group 就按 GID 建 (grp<gid>), 再把 sagemaker-user 加为成员 → sshd
# initgroups() 登录时能解析到这些组。幂等 (getent 判存在), 失败不阻断 (|| true)。
# ⚠️ 不跳过主组: runAsGroup (如 5001=team-a) 常不在镜像 /etc/group 里, sshd 登录
#    主组取自 /etc/passwd (=100 users), 故 runAsGroup 那个 GID 也必须补进 /etc/group,
#    否则该 FSx team 目录 (mode 2770 组=runAsGroup) SSH 会话仍进不去。
# ⚠️ 必须 sudo: postStart 以容器 uid=1000 (runAsUser) 跑, groupadd/usermod 改
#    /etc/group 需 root → 免密 sudo (镜像自带, 同 start-native-ssh-runtime.sh)。
#    不加 sudo 会 "groupadd: Permission denied" 被 || true 静默吞掉 → 组建不出。
GRP_SYNC = (
    "for g in $(id -G); do "
    "getent group \"$g\" >/dev/null 2>&1 || sudo groupadd -g \"$g\" \"grp$g\" 2>/dev/null; "
    "sudo usermod -aG \"$g\" sagemaker-user 2>/dev/null || true; "
    "done; "
)

SEED_SCRIPT = (
    "H=/home/sagemaker-user; "
    "[ -d /etc/skel ] && cp -rn /etc/skel/. $H/ 2>/dev/null; "
    "[ -d /opt/amazon/sagemaker/workspace/skel ] && "
    "cp -rn /opt/amazon/sagemaker/workspace/skel/. $H/ 2>/dev/null; "
    "chown -R 1000:100 $H 2>/dev/null; "
    + GRP_SYNC +
    "exit 0"
)

# 作为 spec.lifecycle.postStart.exec.command 数组直接传给 CR
SEED_COMMAND: list[str] = ["/bin/bash", "-c", SEED_SCRIPT]
