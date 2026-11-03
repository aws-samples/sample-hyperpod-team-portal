"""FSx 目录配额编排: 建目录 / 改配额 / 读用量。

gid/pid 建目录时实时探 FS 取 max+1 (不落库)。所有命令走 fsx-admin pod
(挂 FSx 根 + CAP_SYS_ADMIN)。命令拼装提成纯函数便于单测。
"""

from __future__ import annotations

import asyncio
import re

from app.adapters.aws import fsx as fsx_adapter
from app.core.i18n import t
from app.core.logging import get_logger
from app.modules.fsx_quota.domain.parsing import (
    gib_to_kb,
    kb_to_gib,
    next_id_from,
    parse_dir_rows,
    parse_lfs_quota,
    soft_from_hard,
)
from app.modules.fsx_quota.orchestration.admin_exec import run_admin_cmd
from app.modules.workspace.orchestration.fsx import _sanitize_fsx_subpath

logger = get_logger(__name__)

# 多 FSx: 每块盘在 fsx-admin pod 里挂 /fsx-mnt/<fs-id> (规整后, 不再单块 /fsx)。
# 配额操作都要指明是哪块盘 → 传 fs_id, 直接拼 root (fs-id 天然路径安全)。
_FSX_MNT_BASE = "/fsx-mnt"


async def _fsx_root(filesystem_id: str) -> str:
    """拼 fsx-admin pod 内的挂载根 /fsx-mnt/<fs-id>。

    未在 PLATFORM_FSX_FILESYSTEMS 里配 → 报错 (配额只管平台接入的盘)。
    """
    if not fsx_adapter.is_configured_filesystem(filesystem_id):
        raise FsxQuotaError(t("fsx_quota.not_configured", filesystem_id=filesystem_id))
    return f"{_FSX_MNT_BASE}/{filesystem_id}"

# 目录名会被 UNQUOTED 拼进 fsx-admin pod (CAP_SYS_ADMIN + FSx 根) 里执行的 shell,
# 允许任何 shell 元字符 (; $ 空格 等) 都是命令注入。allowlist 是安全底线。
_DIR_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# gid 从 5001 起 (next_id_from 默认), pid 从 6001 起 —— 分不同千位段, 一眼区分。
_PID_BASE = 6001


class FsxQuotaError(Exception):
    """配额操作失败 (exec 失败 / 校验失败 / lfs 报错)。message 直接给前端。"""


async def _fs_total_gib(filesystem_id: str) -> int | None:
    """指定 FSx 的真实总容量 (StorageCapacity)。拿不到 → None (不阻断列表/校验降级)。"""
    try:
        fs = await fsx_adapter.describe_filesystem(filesystem_id)
        return fs.get("capacity_gib")
    except Exception:  # noqa: BLE001 - 拿不到总容量不阻断列表, 校验降级放行
        return None


def check_quota_sum_ok(
    new_hard_gib: int, other_hard_gibs: list[int], total_gib: int | None
) -> None:
    """所有目录 hard 之和不得超过 FS 总容量。超过则抛 FsxQuotaError。

    total_gib None → 跳过校验 (拿不到总容量时不阻断)。
    """
    if total_gib is None:
        return
    projected = sum(other_hard_gibs) + new_hard_gib
    if projected > total_gib:
        raise FsxQuotaError(
            t(
                "fsx_quota.quota_sum_exceeded",
                projected=projected,
                total=total_gib,
                others=sum(other_hard_gibs),
            )
        )


def validate_dir_name(name: str) -> str:
    """校验目录名: 单段 (不含 /), 拒 .. / 空 / 非法字符。"""
    safe = _sanitize_fsx_subpath(name)  # 拒 .. / 绝对路径 / \x00
    if not safe or "/" in safe:
        raise ValueError(t("fsx_quota.dir_name_not_single", name=repr(name)))
    # 严格 allowlist: 名字会被 unquoted 拼进 root shell, 拒一切非 [字母数字._-] 的字符
    if not _DIR_NAME_RE.match(safe):
        raise ValueError(t("fsx_quota.dir_name_charset"))
    return safe


def build_setquota_cmd(pid: int, hard_gib: int, root: str) -> str:
    """拼 lfs setquota (建/改共用)。-b soft(hard×80%) -B hard。root=盘的挂载根。"""
    soft = soft_from_hard(hard_gib)
    return f"lfs setquota -p {pid} -b {soft}G -B {hard_gib}G {root}"


def build_create_cmd(name: str, gid: int, pid: int, hard_gib: int, root: str) -> str:
    """拼建目录整串: mkdir → chown → chmod setgid → lfs project → setquota。

    && 串联, 任一步失败整体 fail (exec 返 None)。root=盘的挂载根。
    """
    d = f"{root}/{name}"
    return (
        f"mkdir {d} "
        f"&& chown :{gid} {d} "
        f"&& chmod 2770 {d} "
        f"&& lfs project -p {pid} -r -s {d} "
        f"&& {build_setquota_cmd(pid, hard_gib, root)}"
    )


def build_onboard_cmd(name: str, pid: int, hard_gib: int, root: str) -> str:
    """拼 "旧目录首次纳管" 整串: 先递归打 project tag 再 setquota。

    迁入的旧目录 pid==0 (从未打过 tag), 改配额前须先 lfs project -r -s 递归
    打号 (含已有文件) 才能挂配额。&& 串联, 任一步失败整体 fail。root=盘的挂载根。
    """
    return (
        f"lfs project -p {pid} -r -s {root}/{name} "
        f"&& {build_setquota_cmd(pid, hard_gib, root)}"
    )


_OK_SENTINEL = "__FSXQ_OK__"


async def _run_write_and_readback(
    cmd: str, pid: int, root: str, timeout: int
) -> tuple[int, int, int]:
    """执行写命令 + 成功哨兵 + 同趟回读 quota, 一次 exec 搞定 (省一次 pod 握手)。

    输出: "__FSXQ_OK__\\n<lfs quota 表>"。哨兵在前判成败 (写命令静默成功时
    exec_in_pod 返 None, 无法与 pod 不可用区分); quota 表在后供 parse_lfs_quota
    回读校验。失败 (无哨兵/None) 抛 FsxQuotaError。root=盘的挂载根。
    """
    full = f"{cmd} && echo {_OK_SENTINEL} && lfs quota -p {pid} {root}"
    out = await run_admin_cmd(full, timeout=timeout)
    if out is None or _OK_SENTINEL not in out:
        raise FsxQuotaError(t("fsx_quota.admin_unavailable"))
    return parse_lfs_quota(out)


def _dir_record(name: str, gid: int, pid: int, used_kb: int, soft_kb: int, hard_kb: int) -> dict:
    hard_gib = kb_to_gib(hard_kb)
    used_gib = kb_to_gib(used_kb)
    pct = round(used_gib / hard_gib * 100, 1) if hard_gib > 0 else 0.0
    return {
        "name": name,
        "gid": gid,
        "pid": pid,
        "used_gib": round(used_gib, 2),
        "soft_gib": round(kb_to_gib(soft_kb), 2),
        "hard_gib": round(hard_gib, 2),
        "pct": pct,
    }


# 一趟 shell: 列一级目录 + 每个目录 gid/pid/quota 全拉回, 单次 exec 搞定。
# 单次 kubectl exec 到 EKS pod 的 websocket 握手 ~3.6s, 逐目录多次 exec 会叠成
# 数秒~十几秒; 合并成 1 次后墙钟 ≈ 一次 exec。输出行: name|gid|pid|used,soft,hard。
# root=盘的挂载根 (/fsx-mnt/<fs-id>)。
# ⚠️ lfs quota 输出: 路径短时 Filesystem 和数值同一行 (数值在 $2,$3,$4); 路径长
# (/fsx-mnt/<fs-id>) 时 Filesystem 单独一行, 数值另起一行 (数值在 $1,$2,$3)。awk
# 两种都兼容: 首列是路径 (/开头) → 取 $2,$3,$4; 首列是数字 (换行后的数值行) → 取 $1,$2,$3。
def _list_dirs_sh(root: str) -> str:
    return (
        f'for d in "{root}"/*/; do '
        '[ -d "$d" ] || continue; '
        'n=$(basename "$d"); '
        'g=$(ls -ldn "$d" | awk "{print \\$4}"); '
        'p=$(lfs project -d "$d" | awk "{print \\$1}"); '
        'q=""; '
        '[ "$p" != "0" ] && q=$(lfs quota -p "$p" '
        f'{root} 2>/dev/null | awk \''
        'index($1,"/")==1 && NF>=4 {print $2","$3","$4; exit} '
        '$1 ~ /^[0-9]+\\*?$/ {print $1","$2","$3; exit}\'); '
        'printf "%s|%s|%s|%s\\n" "$n" "$g" "$p" "$q"; '
        "done"
    )


async def list_directories(filesystem_id: str) -> dict:
    """列指定 FSx 各一级目录用量 + FS 总容量。source of truth = FS。

    目录探测走单趟 shell (一次 exec 拉全部, 避免逐目录多次 exec —— 单次 exec
    到 pod ~3.6s, 目录多时页面加载数秒)。总容量 (AWS describe) 与之并发。
    """
    root = await _fsx_root(filesystem_id)
    out_task = run_admin_cmd(_list_dirs_sh(root), timeout=15)
    total_task = _fs_total_gib(filesystem_id)
    out, total_gib = await asyncio.gather(out_task, total_task)
    rows = parse_dir_rows(out or "")
    directories = [
        _dir_record(name, gid, pid, used_kb, soft_kb, hard_kb)
        for name, gid, pid, used_kb, soft_kb, hard_kb in rows
    ]
    return {"total_gib": total_gib, "directories": directories}


def resolve_gid(requested_gid: int | None, existing_gids: set[int]) -> int:
    """定 gid: 不传 → 自动新分配 (新 team); 传已有 → 复用; 传未知 → 拒。

    纯决策逻辑 (无 IO), 便于单测。复用校验防 typo 造孤儿组。
    """
    if requested_gid is None:
        return next_id_from(sorted(existing_gids))
    if requested_gid not in existing_gids:
        raise FsxQuotaError(t("fsx_quota.gid_unknown", gid=requested_gid))
    return requested_gid


async def create_directory(
    filesystem_id: str, name: str, hard_gib: int, gid: int | None = None
) -> dict:
    """在指定 FSx 建目录: 定 gid/探 pid → 建 → 回读校验。

    gid = 复用 team 归属 (传已有 gid 则新目录加入该 team, 共享组权限);
    不传则自动新分配一个 (新 team)。
    pid = 独立配额, 永远新分配, 与 gid 解耦 —— 复用 gid 也拿自己的 project id。
    """
    root = await _fsx_root(filesystem_id)
    safe = validate_dir_name(name)
    # 一趟 shell 拿全部现存目录 gid/pid/hard (避免逐目录多次 exec —— 单次到 pod
    # ~3.6s, 老实现 create 要 ~20 次串行 exec 数十秒), 与总容量 (AWS) 并发。
    rows_out, total_gib = await asyncio.gather(
        run_admin_cmd(_list_dirs_sh(root), timeout=15), _fs_total_gib(filesystem_id)
    )
    rows = parse_dir_rows(rows_out or "")
    if any(n == safe for n, *_ in rows):
        raise FsxQuotaError(t("fsx_quota.dir_exists", name=safe))

    gid = resolve_gid(gid, {r[1] for r in rows})  # r[1]=gid

    # 配额总和校验: 现有各目录 hard 之和 + 新目录 hard 不得超 FS 总容量 (fail fast)。
    others = [int(kb_to_gib(r[5])) for r in rows]  # r[5]=hard_kb
    check_quota_sum_ok(hard_gib, others, total_gib)

    # pid 独立分配 (与 gid 解耦), 现存 pid max+1; base=6001 与 gid(5001) 分段
    pid = next_id_from([r[2] for r in rows], base=_PID_BASE)  # r[2]=pid

    # 建目录 + setquota + 哨兵 + 回读, 一次 exec 完成 (省单独回读的一次 pod 握手)。
    cmd = build_create_cmd(safe, gid, pid, hard_gib, root)
    try:
        used_kb, soft_kb, hard_kb = await _run_write_and_readback(cmd, pid, root, timeout=15)
    except FsxQuotaError as exc:
        raise FsxQuotaError(t("fsx_quota.create_failed", name=safe, error=exc)) from exc
    # Lustre 可能把限额上取整到 OST/qunit 边界, 回读会 >= 请求值。只有小于请求
    # (配额没设成/设小了) 才算失败。
    if hard_kb < gib_to_kb(hard_gib):
        raise FsxQuotaError(
            t(
                "fsx_quota.create_readback_failed",
                expected=hard_gib,
                actual=kb_to_gib(hard_kb),
            )
        )
    logger.info("fsx_quota.create.ok", name=safe, gid=gid, pid=pid, hard_gib=hard_gib)
    return _dir_record(safe, gid, pid, used_kb, soft_kb, hard_kb)


async def update_quota(filesystem_id: str, name: str, hard_gib: int) -> dict:
    """改指定 FSx 目录配额: 探 pid → 重跑 setquota → 回读。不动 gid/目录。

    pid==0 的旧目录 (迁入时从未打过 tag) 在本次调用里顺带纳管: 分配新 pid →
    递归打 tag → setquota, 而非直接报错。
    """
    root = await _fsx_root(filesystem_id)
    safe = validate_dir_name(name)
    # 一趟 shell 拿全部现存目录 gid/pid/hard, 与总容量 (AWS) 并发 (省掉逐目录多次 exec)。
    rows_out, total_gib = await asyncio.gather(
        run_admin_cmd(_list_dirs_sh(root), timeout=15), _fs_total_gib(filesystem_id)
    )
    rows = parse_dir_rows(rows_out or "")
    match = [r for r in rows if r[0] == safe]
    if not match:
        raise FsxQuotaError(t("fsx_quota.dir_not_found", name=safe))
    gid = match[0][1]  # r[1]=gid
    pid = match[0][2]  # r[2]=pid (0 = 未纳管)

    # 配额总和校验: 排除自己 (旧配额将被新值替换), 其余 hard 之和 + 新值不得超总容量。
    others = [int(kb_to_gib(r[5])) for r in rows if r[0] != safe]  # r[5]=hard_kb
    check_quota_sum_ok(hard_gib, others, total_gib)

    if pid == 0:
        # 从未纳管: 现存 pid max+1 分配, 保证不撞号 (复用同一份快照)。base=6001 与 gid 分段。
        pid = next_id_from([r[2] for r in rows], base=_PID_BASE)
        # 递归打 tag (含已有文件) 可能耗时, timeout 放宽到 15s。
        cmd = build_onboard_cmd(safe, pid, hard_gib, root)
        timeout = 15
        onboarded = True
    else:
        # 已纳管: 仅重跑 setquota。
        cmd = build_setquota_cmd(pid, hard_gib, root)
        timeout = 10
        onboarded = False

    # setquota/纳管 + 哨兵 + 回读, 一次 exec 完成 (省单独回读的一次 pod 握手)。
    try:
        used_kb, soft_kb, hard_kb = await _run_write_and_readback(cmd, pid, root, timeout=timeout)
    except FsxQuotaError as exc:
        raise FsxQuotaError(t("fsx_quota.update_failed", error=exc, name=safe)) from exc
    # Lustre 可能上取整限额, 回读 >= 请求即视为成功; 仅小于才算没设成。
    if hard_kb < gib_to_kb(hard_gib):
        raise FsxQuotaError(
            t(
                "fsx_quota.update_readback_failed",
                expected=hard_gib,
                actual=kb_to_gib(hard_kb),
            )
        )
    event = "fsx_quota.update.onboarded" if onboarded else "fsx_quota.update.ok"
    logger.info(event, name=safe, pid=pid, hard_gib=hard_gib)
    return _dir_record(safe, gid, pid, used_kb, soft_kb, hard_kb)
