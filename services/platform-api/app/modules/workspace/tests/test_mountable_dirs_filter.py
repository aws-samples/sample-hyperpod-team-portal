"""mountable-dirs: 只返回 gid==primary_gid 的目录; primary_gid 空则空。"""
from app.modules.workspace.api.fsx_router import _filter_dirs_by_primary_gid


def _dir(name, gid):
    return {"name": name, "gid": gid}


def test_filter_keeps_matching_gid():
    dirs = [_dir("a", 1001), _dir("b", 2002), _dir("c", 1001)]
    out = _filter_dirs_by_primary_gid(dirs, 1001)
    assert [d["name"] for d in out] == ["a", "c"]


def test_filter_empty_when_primary_gid_none():
    dirs = [_dir("a", 1001)]
    assert _filter_dirs_by_primary_gid(dirs, None) == []


def test_filter_empty_when_no_match():
    dirs = [_dir("a", 2002)]
    assert _filter_dirs_by_primary_gid(dirs, 1001) == []
