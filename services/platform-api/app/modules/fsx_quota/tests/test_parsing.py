from app.modules.fsx_quota.domain.parsing import (
    next_id_from,
    parse_dir_rows,
    parse_ls_dirs,
    parse_lfs_project_pid,
    parse_lfs_quota,
    soft_from_hard,
    gib_to_kb,
    kb_to_gib,
)


def test_parse_dir_rows_full():
    # 一趟 shell 汇总: name|gid|pid|used,soft,hard
    out = (
        "team-a|5001|5001|2751132,167772160,209715200\n"
        "team-e|5005|5003|104886052*,83886080,104857600\n"
    )
    assert parse_dir_rows(out) == [
        ("team-a", 5001, 5001, 2751132, 167772160, 209715200),
        # 超额尾部 * 被剥离
        ("team-e", 5005, 5003, 104886052, 83886080, 104857600),
    ]


def test_parse_dir_rows_untagged_no_quota():
    # pid=0 (未纳管) → quota 段为空 → used/soft/hard 记 0
    assert parse_dir_rows("team-c|5003|0|\n") == [("team-c", 5003, 0, 0, 0, 0)]


def test_parse_dir_rows_skips_garbage():
    out = "team-a|5001|5001|10,20,30\nbad-line\nno|enough\n"
    assert parse_dir_rows(out) == [("team-a", 5001, 5001, 10, 20, 30)]


def test_next_id_empty_starts_at_base():
    assert next_id_from([], base=5001) == 5001


def test_next_id_ignores_below_base():
    # 系统 gid (< 5001) 被忽略, 从 5001 起
    assert next_id_from([0, 1000, 100], base=5001) == 5001


def test_next_id_max_plus_one():
    assert next_id_from([5001, 5002, 3], base=5001) == 5003


def test_parse_ls_dirs():
    out = "team-a|5001\nteam-b|5002\n"
    assert parse_ls_dirs(out) == [("team-a", 5001), ("team-b", 5002)]


def test_parse_ls_dirs_skips_garbage():
    out = "team-a|5001\ngarbage-no-pipe\nteam-b|notanum\n"
    assert parse_ls_dirs(out) == [("team-a", 5001)]


def test_parse_lfs_project_pid():
    # `lfs project -d /fsx/team-a` → "5001 P /fsx/team-a"
    assert parse_lfs_project_pid("5001 P /fsx/team-a") == 5001


def test_parse_lfs_project_pid_untagged():
    # 无 project tag → pid 0
    assert parse_lfs_project_pid("0 - /fsx/loose") == 0
    assert parse_lfs_project_pid("") == 0


def test_parse_lfs_quota():
    # lfs quota -p 5001 /fsx 表格行: fs used soft hard grace files ...
    # 数值单位 kbytes. 取 used/soft/hard.
    out = (
        "Disk quotas for prj 5001 (pid 5001):\n"
        "     Filesystem  kbytes   quota   limit   grace   files   quota   limit   grace\n"
        "           /fsx  1048576 838860 1048576       -      12       0       0       -\n"
    )
    assert parse_lfs_quota(out) == (1048576, 838860, 1048576)


def test_parse_lfs_quota_garbage():
    assert parse_lfs_quota("no data") == (0, 0, 0)


def test_parse_lfs_quota_over_quota_marker():
    # 超额时 lfs 在数值尾部打 `*` (如 1100000*), 不能因此丢数字
    out = (
        "Disk quotas for prj 5001 (pid 5001):\n"
        "     Filesystem  kbytes   quota   limit   grace   files\n"
        "           /fsx  1100000* 838860 1048576       -      12\n"
    )
    assert parse_lfs_quota(out) == (1100000, 838860, 1048576)


def test_soft_from_hard():
    assert soft_from_hard(100) == 80
    assert soft_from_hard(10) == 8


def test_gib_kb_roundtrip():
    assert gib_to_kb(1) == 1048576
    assert kb_to_gib(1048576) == 1.0
