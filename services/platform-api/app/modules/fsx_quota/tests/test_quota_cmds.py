import pytest

from app.modules.fsx_quota.orchestration.quota import (
    FsxQuotaError,
    build_create_cmd,
    build_onboard_cmd,
    build_setquota_cmd,
    resolve_gid,
    validate_dir_name,
)


_ROOT = "/fsx-mnt/fs-0c0b1234567890abc"  # 多 FSx: 挂载根 = /fsx-mnt/<fs-id>


def test_build_setquota_soft_is_80pct():
    cmd = build_setquota_cmd(pid=5001, hard_gib=100, root=_ROOT)
    # soft = 80G, hard = 100G
    assert "-b 80G" in cmd
    assert "-B 100G" in cmd
    assert "-p 5001" in cmd
    assert cmd.rstrip().endswith(_ROOT)


def test_build_create_cmd_has_all_steps():
    cmd = build_create_cmd(name="team-x", gid=5003, pid=5003, hard_gib=50, root=_ROOT)
    assert f"mkdir {_ROOT}/team-x" in cmd
    assert f"chown :5003 {_ROOT}/team-x" in cmd
    assert f"chmod 2770 {_ROOT}/team-x" in cmd
    assert f"lfs project -p 5003 -r -s {_ROOT}/team-x" in cmd
    assert "-b 40G" in cmd and "-B 50G" in cmd
    # 各步用 && 串, 任一失败整体 fail
    assert "&&" in cmd


def test_build_onboard_cmd():
    # pid==0 的旧目录: 先递归打 tag 再 setquota, && 串联
    cmd = build_onboard_cmd(name="team-a", pid=5005, hard_gib=100, root=_ROOT)
    # 先打 tag (递归 -r + set-inherit -s)
    assert f"lfs project -p 5005 -r -s {_ROOT}/team-a" in cmd
    # 再 setquota (soft=hard×80%)
    assert "-b 80G" in cmd and "-B 100G" in cmd
    assert cmd.rstrip().endswith(_ROOT)
    # tag 在 setquota 之前, && 串联
    assert "&&" in cmd
    assert cmd.index("lfs project") < cmd.index("setquota")


def test_validate_dir_name_ok():
    assert validate_dir_name("team-a") == "team-a"


def test_validate_dir_name_rejects_slash():
    with pytest.raises(ValueError):
        validate_dir_name("a/b")


def test_validate_dir_name_rejects_dotdot():
    with pytest.raises(ValueError):
        validate_dir_name("..")


def test_validate_dir_name_rejects_empty():
    with pytest.raises(ValueError):
        validate_dir_name("")


def test_validate_dir_name_rejects_semicolon():
    with pytest.raises(ValueError):
        validate_dir_name("a;rm -rf /")


def test_validate_dir_name_rejects_space():
    with pytest.raises(ValueError):
        validate_dir_name("a b")


def test_validate_dir_name_rejects_dollar():
    with pytest.raises(ValueError):
        validate_dir_name("x$(whoami)")


def test_validate_dir_name_allows_normal():
    assert validate_dir_name("team-a.v2_1") == "team-a.v2_1"


def test_resolve_gid_none_allocates_new():
    # 不传 gid → 新建 team, 现存 max+1
    assert resolve_gid(None, {5001, 5002}) == 5003


def test_resolve_gid_reuse_existing():
    # 传已有 gid → 复用该 team 归属
    assert resolve_gid(5001, {5001, 5002}) == 5001


def test_resolve_gid_reject_unknown():
    # 传未知 gid → 拒 (防 typo 造孤儿组)
    with pytest.raises(FsxQuotaError):
        resolve_gid(9999, {5001, 5002})


def test_resolve_gid_none_empty():
    # 无现存目录且不传 → base
    assert resolve_gid(None, set()) == 5001
