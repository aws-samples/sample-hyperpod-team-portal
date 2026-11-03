"""FSx 配额相关命令输出解析 + id 分配 (纯函数, 零 IO).

集中放这里便于单测: 直接喂固定命令输出串断言, 不 mock exec
(与 workspace/tests/test_probe_dir_gid.py 同模式)。
"""

from __future__ import annotations

_KB_PER_GIB = 1048576
# 一趟 shell 汇总输出的字段分隔符 / quota 段分隔符 (parse_dir_rows 用)。


def next_id_from(existing: list[int], base: int = 5001) -> int:
    """从现有 id 里取下一个可用值: >= base 的最大值 +1, 无则 base。

    gid/pid 都不落库, 建目录时实时探 FS 现状取 max+1。base=5001 避开系统 gid。
    删目录后号会被重用 (旧目录已不存在, 无害)。
    """
    candidates = [x for x in existing if x >= base]
    return (max(candidates) if candidates else base - 1) + 1


def parse_ls_dirs(out: str) -> list[tuple[str, int]]:
    """解析 "<name>|<gid>" 多行输出 → [(name, gid)]。非法行跳过。"""
    result: list[tuple[str, int]] = []
    for line in (out or "").strip().splitlines():
        if "|" not in line:
            continue
        name, gid_str = line.rsplit("|", 1)
        name = name.strip()
        try:
            gid = int(gid_str.strip())
        except ValueError:
            continue
        if name:
            result.append((name, gid))
    return result


def parse_lfs_project_pid(out: str) -> int:
    """`lfs project -d <dir>` 输出首列是 project id。无 tag/解析失败 → 0。

    输出形如: "5001 P /fsx/team-a" (pid, flag, path)。
    """
    line = (out or "").strip().splitlines()
    if not line:
        return 0
    parts = line[0].split()
    if not parts:
        return 0
    try:
        return int(parts[0])
    except ValueError:
        return 0


def _to_int(s: str) -> int:
    """去掉超额标记再转 int。lfs 在超限数值尾部打单个 `*` (如 1100000*),
    直接 int() 会炸。真正的垃圾仍走 ValueError 由调用方兜底。
    """
    return int(s.rstrip("*"))


def parse_lfs_quota(out: str) -> tuple[int, int, int]:
    """`lfs quota -p <pid> <root>` → (used_kb, soft_kb, hard_kb)。

    ⚠️ 挂载根路径较长时 (如 /fsx-mnt/<fs-id>) lfs 会把 Filesystem 单独放一行,
    数值另起一行 (首列是 used_kb 数字, 不是路径)。故不能靠 "行首是 /" 定位数据行,
    改为: 找首字段是数字 (可含尾部 * 超额标记) 且后面至少还有 2 个数字的行。
    超额值尾部 `*` 需剥离。解析失败 → (0, 0, 0)。
    """
    for line in (out or "").splitlines():
        parts = line.split()
        # inline (路径短, 同行): "/fsx <used> <soft> <hard> ..." → 取 [1],[2],[3]
        if len(parts) >= 4 and parts[0].startswith("/"):
            try:
                return (_to_int(parts[1]), _to_int(parts[2]), _to_int(parts[3]))
            except ValueError:
                continue
        # wrapped (路径长, 数值另起一行): "<used> <soft> <hard> ..." → 取 [0],[1],[2]
        if len(parts) >= 3 and parts[0].rstrip("*").isdigit():
            try:
                return (_to_int(parts[0]), _to_int(parts[1]), _to_int(parts[2]))
            except ValueError:
                continue
    return (0, 0, 0)


def parse_dir_rows(out: str) -> list[tuple[str, int, int, int, int, int]]:
    """解析一趟 shell 汇总输出 → [(name, gid, pid, used_kb, soft_kb, hard_kb)]。

    每行格式: "<name>|<gid>|<pid>|<used>,<soft>,<hard>"
    (fsx-admin 里一次循环列全部目录, 避免逐目录多次 exec —— 单次 exec ~3.6s)。
    pid==0 (未纳管) 或 quota 段缺失 → used/soft/hard 记 0。超额值尾部 `*` 剥离。
    非法行跳过。
    """
    result: list[tuple[str, int, int, int, int, int]] = []
    for line in (out or "").strip().splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        name = parts[0].strip()
        if not name:
            continue
        try:
            gid = int(parts[1].strip())
            pid = int(parts[2].strip())
        except ValueError:
            continue
        used_kb = soft_kb = hard_kb = 0
        q = parts[3].strip()
        if q:
            nums = q.split(",")
            if len(nums) == 3:
                try:
                    used_kb, soft_kb, hard_kb = (
                        _to_int(nums[0]),
                        _to_int(nums[1]),
                        _to_int(nums[2]),
                    )
                except ValueError:
                    used_kb = soft_kb = hard_kb = 0
        result.append((name, gid, pid, used_kb, soft_kb, hard_kb))
    return result


def soft_from_hard(hard_gib: int) -> int:
    """soft 告警线 = hard × 80% 向下取整。"""
    return int(hard_gib * 0.8)


def gib_to_kb(gib: int) -> int:
    return gib * _KB_PER_GIB


def kb_to_gib(kb: int) -> float:
    return kb / _KB_PER_GIB
