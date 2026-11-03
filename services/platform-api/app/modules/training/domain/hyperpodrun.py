"""把用户命令包装成 `hyperpodrun` 入口 · 纯函数.

HyperPod Training Operator 要求每个 Pod 里监听 :8080 的 HyperPodElasticAgent,
而 agent 的启动入口是 `hyperpodrun` (替代 torchrun). 如果用户命令里已经
自己写了 `hyperpodrun`, 我们尊重用户; 否则 wrapper 负责:

1. 在 Pod 启动时装 ``hyperpod-elastic-agent`` wheel (一次, ~15s)
2. 把用户命令持久化到容器内脚本
3. 以 `hyperpodrun ... <script>` 形式 exec, 让 agent 托管生命周期

Sources (verified 2026-05-11 on pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime):
- https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-eks-operator-usage.html
- https://github.com/aws/sagemaker-hyperpod-training-operator
"""

from __future__ import annotations

# 用户命令落盘路径. 外部测试也要用, 所以暴露成常量.
USER_SCRIPT_PATH = "/tmp/platform/user_script.py"


_SHELL_OPERATORS = ("&&", "||", ";", "|", ">", "<", "$(")

# hyperpodrun / hyperpod-elastic-agent 训完自己给自己发 SIGTERM, Python uncaught
# raise SignalException 写一段 stack 到 stderr (uvicorn lifespan + torch elastic +
# hyperpod_elastic_agent + starlette + asyncio CancelledError). 这些不是真错,
# 用户看着像 fail. [待解决].
#
# 不改 train.py / 不改 hyperpod-elastic-agent 的前提下, 用 bash process substitution
# 把 hyperpodrun 自己的 stderr 单走 grep -vE 过滤这些已知收尾 stack 行. NCCL /
# accelerate / 用户训练 stderr 仍透传 (pattern 不命中).
#
# 风险: 真训练失败时 SignalException 也可能不同步出现, 但本 pattern 极特异
# (uvicorn/lifespan + receive_queue.get + Process N got signal: 15) 几乎不会误过滤
# 真业务错.
_SIGTERM_FILTER_PAT = (
    r"Received 15 death signal|"
    r"asyncio\.exceptions\.CancelledError|"
    r"SignalException: Process [0-9]+ got signal|"
    r"Shutdown completed for signal SIGTERM|"
    r"INFO: +Shutting down|"
    r"INFO: +Finished server process|"
    r"starlette/routing\.py|"
    r"uvicorn/lifespan|"
    r"hyperpod_elastic_agent/(run|elastic_agent)|"
    r"torch/distributed/elastic/(multiprocessing|agent)|"
    r"raise SignalException|"
    r"^\s*await (receive|getter)|"
    r"^\s*return await self\.receive_queue|"
    r"^\s*sys\.exit\(main\(\)\)|"
    r"^\s*run\(args\)|"
    r"^\s*result = (agent\.run|f\(\*args|self\._invoke_run)|"
    r"^\s*time\.sleep\(monitor_interval\)"
)
# bash process substitution 把 stderr 喂过滤管道:
#   1. awk 见 "Received 15 death signal" 标记后直接吞掉余下所有行 (训完收尾段).
#   2. 标记前的 stderr 仍走 grep -vE 反向过滤 (NCCL warn / accelerate 错若混在前面也保留).
# pattern 用单引号包, 内无单引号.
_STDERR_FILTER = (
    " 2> >(awk '"
    "/Received 15 death signal/{seen=1} "
    "!seen{print > \"/dev/stderr\"; fflush()}"
    "' >&2)"
)


def _extract_script_path(cmd: str) -> str:
    """从 "sh|bash <abs-path> [args]" 提取【绝对路径】脚本文件 (防套娃运行时探测目标)。

    兜底分支命令典型形态: "sh /fsx/code/run.sh" / "bash /fsx/x.sh --arg".
    取首个 token (sh/bash) 后的、以 .sh 结尾的 token 当脚本路径。

    ★只认绝对路径 (以 / 开头): 相对路径 (run.sh / ./x.sh) 运行时 CWD 不定, grep
    不到文件 → 探测必失效 → 与其假装能防, 不如返回空跳过探测 (退化为原套壳行为).
    前端方式A (buildScriptCommand) 永远生成绝对路径 sh /fsx/...; 套娃主场景全覆盖.
    取不到 (非 sh/bash 命令 / 无 .sh token / 相对路径) 返回空串 → 调用方跳过探测.
    """
    parts = cmd.strip().split()
    if not parts or parts[0] not in ("sh", "bash", "/bin/sh", "/bin/bash"):
        return ""
    for tok in parts[1:]:
        # 跳过 -c / -lc 等 flag; 命中首个 .sh 文件 token
        if tok.startswith("-"):
            continue
        # 只认绝对路径 .sh (相对路径运行时 grep 不到, 诚实跳过)
        if tok.endswith(".sh") and tok.startswith("/"):
            return tok
        # 第一个非 flag token 不是绝对 .sh (相对路径 / 内联串) → 放弃
        return ""
    return ""


def _is_pure_python_invocation(cmd: str) -> bool:
    """是不是 'python xxx.py [args]' 这种纯 python 调用 (能直接喂 hyperpodrun).

    含 shell 操作符 / pip / cd / export 都算 shell, 必须走 --no-python bash 分支.
    """
    s = cmd.strip()
    for op in _SHELL_OPERATORS:
        if op in s:
            return False
    first = s.split(None, 1)[0] if s else ""
    return first.startswith("python")


# hyperpodrun 默认日志目录 (torch elastic --tee=3 把每 rank stdout/stderr 写这).
# /tmp 是 pod 临时盘, pod 删即丢. 挂了 FSx 时由 cr.py 传 /fsx/outputs/<job>/logs
# (持久, 每 rank 一文件), 实现"平台自动全量归档训练日志到 FSx" (不依赖用户改代码).
_DEFAULT_LOG_DIR = "/tmp/hyperpod"


def wrap_with_hyperpodrun(
    user_command: str, gpu_per_node: int, log_dir: str = _DEFAULT_LOG_DIR
) -> str:
    """Wrap user command with hyperpod-elastic-agent launcher.

    HyperPod operator hyperpodrun 默 entrypoint=python3.11 把 training_script 当
    .py 跑. 含 shell 操作符 (&& / pip / cd) 的命令必须走 --no-python + /bin/bash -c.

    Args:
        user_command: 用户训练命令
        gpu_per_node: 每节点 GPU 数, 给 --nproc-per-node
        log_dir: hyperpodrun --log_dir (torch elastic 每 rank stdout/stderr 落盘处).
            挂 FSx 时传 /fsx/outputs/<job>/logs 实现全量持久归档; 否则默 /tmp/hyperpod.

    Returns:
        含 ``hyperpodrun`` 的 shell 脚本. 用户自带 ``hyperpodrun`` 则透传.
    """
    if "hyperpodrun" in user_command:
        return user_command

    nproc = str(gpu_per_node) if gpu_per_node > 0 else "1"
    # log_dir 准备: FSx 多层子目录 hyperpodrun 不自建 → mkdir -p.
    # ★umask 0007: 让 torch elastic 在 log_dir 下建的 attempt/<rank> 目录 + 日志文件
    #   带【组 rwx】. 配合 pod securityContext fsGroup/runAsGroup=team_gid, 日志 team 组可读写.
    # chmod 2770 log_dir: 父目录显式给组 rwx + setgid (子目录继承组).
    # ★后台 chmod 循环 (仅 FSx log_dir): torch elastic 用 tempfile.mkdtemp 建
    #   <log_dir>/<run_id>_xxxx 这层, mkdtemp 硬编码 mode 0700 (Python 标准库写死, 不甩
    #   umask, torch 无参数改) → 开发机同 team 组进不去那层 → 看不到里面 attempt/<rank> 日志.
    #   解法: 后台周期 chmod -R g+rwX 把 mkdtemp 的 0700 实时掰成 0770. setsid 脱离
    #   exec session, pod 死随之结束 (无需清理). 仅 log_dir 在 FSx 时启 (默 /tmp 不需要).
    is_fsx_logdir = not log_dir.startswith("/tmp")
    chmod_daemon = (
        f"setsid sh -c 'while true; do "
        f"chmod -R g+rwX {log_dir} 2>/dev/null || true; sleep 15; "
        f"done' </dev/null >/dev/null 2>&1 &\n"
        if is_fsx_logdir
        else ""
    )
    mkdir_logdir = (
        f"umask 0007\n"
        f"mkdir -p {log_dir}\n"
        f"chmod 2770 {log_dir} 2>/dev/null || true\n"
        f"{chmod_daemon}"
    )

    # 纯 python xxx.py → hyperpodrun 当默 python entrypoint, 直跑
    if _is_pure_python_invocation(user_command):
        # parts[0]=python*  parts[1:]=script + args
        parts = user_command.strip().split()
        py_args = " ".join(parts[1:])  # 含 script path + args
        return (
            "set -e\n"
            "pip install -q hyperpod-elastic-agent 2>&1 | tail -3\n"
            f"{mkdir_logdir}"
            f"exec hyperpodrun --server-host=$HOSTNAME --server-port=8080 "
            f"--tee=3 --log_dir={log_dir} "
            f"--nnodes=$NNODES --nproc-per-node={nproc} "
            f"{py_args}"
            f"{_STDERR_FILTER}"
        )

    # 含 shell 操作符 → 拆 pip 段 + python 段. pip 段在 hyperpodrun 启动**之前**
    # 单进程跑 (容器入口 shell 单实例), 不进入 DDP 4 rank 并发, 避免共享 conda env
    # 互删半装文件 (OSError: pyarrow.so / fsspec / yarl).
    #
    # 启发式: 按最后一个 '&& python' 切. python 段以前 = 准备段 (包括 pip / aws s3 sync /
    # cd 等), python 段及之后 = 训练入口. 只要训练入口在最后, 拆得开.
    py_idx = user_command.rfind("&& python")
    if py_idx >= 0:
        prep_segment = user_command[: py_idx].rstrip().rstrip("&").rstrip()
        train_segment = user_command[py_idx + 3 :].lstrip()  # 跳过 '&& '
        return (
            "set -e\n"
            "pip install -q hyperpod-elastic-agent 2>&1 | tail -3\n"
            f"{mkdir_logdir}"
            # 单进程跑准备段 (pip install / aws s3 sync 等)
            f"{prep_segment}\n"
            # 训练段走 hyperpodrun 4 rank 并发
            f"exec hyperpodrun --server-host=$HOSTNAME --server-port=8080 "
            f"--tee=3 --log_dir={log_dir} "
            f"--nnodes=$NNODES --nproc-per-node={nproc} "
            f"--no-python /bin/bash -c {train_segment!r}"
            f"{_STDERR_FILTER}"
        )

    # 兜底: 用户命令没含 python (典型 "sh /fsx/run.sh" / "bash xxx.sh"), 整条走 bash.
    #
    # ★防套娃 (运行时自适应): 子串匹配 "hyperpodrun" in user_command 只看 command 串,
    #   看不到脚本【文件内容】. 若用户脚本 (如 hypd_run_elastic.sh) 自己已调 hyperpodrun
    #   + 装 agent, 而 command="sh /fsx/run.sh" 不含字样 → 平台又套一层 hyperpodrun →
    #   嵌套 (俩抢 :8080) 崩. 渲染时 FSx 没挂, 后端读不到文件; 但【运行时】文件在 FSx 上
    #   可读 → 容器启动先 grep 命令引用的脚本文件, 自带 hyperpodrun 则直接跑脚本 (不套).
    #
    # 提取脚本路径: 兜底命令形态固定 "sh|bash <path> [args]", 取首个 .sh token 作探测目标.
    # 取不到 (非 sh/bash 命令) → detect_path 为空 → 跳过探测, 照常套 (退化为原行为).
    detect_path = _extract_script_path(user_command)
    self_managed_guard = (
        f"if [ -f {detect_path!r} ] && "
        f"grep -q hyperpodrun {detect_path!r} 2>/dev/null; then\n"
        f"  echo '[platform] The script already runs hyperpodrun itself; not wrapping it again (avoids nesting), executing it directly' >&2\n"
        f"  exec /bin/bash -c {user_command!r}\n"
        f"fi\n"
        if detect_path
        else ""
    )
    return (
        "set -e\n"
        f"{self_managed_guard}"
        "pip install -q hyperpod-elastic-agent 2>&1 | tail -3\n"
        f"{mkdir_logdir}"
        f"exec hyperpodrun --server-host=$HOSTNAME --server-port=8080 "
        f"--tee=3 --log_dir={log_dir} "
        f"--nnodes=$NNODES --nproc-per-node={nproc} "
        f"--no-python /bin/bash -c {user_command!r}"
        f"{_STDERR_FILTER}"
    )
