from app.modules.workspace.orchestration.fsx import _parse_gid_from_ls


def test_parse_gid_from_ls_dn_output():
    # `ls -ldn` 输出第 4 列是 gid (numeric)
    line = "drwxrws--- 2 0 5003 4096 Jun  5 10:00 /fsx/team-c"
    assert _parse_gid_from_ls(line) == 5003


def test_parse_gid_from_ls_empty_returns_none():
    assert _parse_gid_from_ls("") is None


def test_parse_gid_from_ls_garbage_returns_none():
    assert _parse_gid_from_ls("not enough cols") is None
