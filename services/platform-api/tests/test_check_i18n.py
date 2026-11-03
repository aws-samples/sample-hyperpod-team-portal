"""scripts/check_i18n.py 守门规则单测。"""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_i18n", Path(__file__).resolve().parents[1] / "scripts" / "check_i18n.py"
)
check_i18n = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_i18n)  # type: ignore[union-attr]


def _lines(src: str) -> list[int]:
    return [ln for ln, _ in check_i18n.violations(src)]


def test_flags_http_detail():
    assert check_i18n.violations('raise HTTPException(403, "无权访问")\n') == [(1, "无权访问")]


def test_flags_each_fstring_fragment():
    assert _lines('x = f"任务 {a} 不存在"\n') == [1, 1]


def test_flags_value_error():
    assert _lines('raise ValueError("必须是相对路径")\n') == [1]


def test_exempts_docstrings_and_bare_strings():
    src = 'def f():\n    """中文说明"""\n    return 1\nX = 1\n"""属性文档串"""\n'
    assert check_i18n.violations(src) == []


def test_exempts_logger_calls():
    assert check_i18n.violations('logger.info("中文日志", x=1)\n') == []


def test_exempts_openapi_calls_and_decorators():
    src = (
        'a: int = Field(description="中文")\n'
        '@router.get("/x", summary="中文", responses={403: {"description": "无权"}})\n'
        "async def h():\n"
        "    return 1\n"
    )
    assert check_i18n.violations(src) == []


def test_exempts_marked_statement():
    src = '_DESC = (  # i18n-exempt: openapi\n    "第一行"\n    "第二行"\n)\n'
    assert check_i18n.violations(src) == []


def test_marker_on_other_statement_does_not_leak():
    src = 'a = "甲"  # i18n-exempt: openapi\nb = "乙"\n'
    assert _lines(src) == [2]


def test_ignores_non_cjk():
    assert check_i18n.violations('raise HTTPException(404, "not found")\n') == []


def test_flags_fullwidth_punctuation_only():
    assert _lines('x = "（"\n') == [1]


def test_marker_on_non_first_line_does_not_exempt():
    src = 'raise HTTPException(\n    403,\n    "中文",  # i18n-exempt: openapi\n)\n'
    assert _lines(src) == [3]


def test_openapi_exemption_is_narrowed_to_description_kwargs():
    assert check_i18n.violations('x = Query("默认值", description="说明")\n') == [(1, "默认值")]
    assert _lines('x = Field(default="中文")\n') == [1]
    assert _lines('p = Path("/data/中文")\n') == [1]


def test_cli_rejects_bad_usage():
    assert check_i18n.main(["--bogus"]) == 2
    assert check_i18n.main(["-h"]) == 2
    assert check_i18n.main(["app/definitely-not-here"]) == 2


def test_iter_files_excludes_tests_main_and_locales():
    rels = [p.relative_to(check_i18n.ROOT).as_posix() for p in check_i18n.iter_files([])]
    assert rels
    assert not any("/tests/" in r for r in rels)
    assert "app/main.py" not in rels
    assert not any(r.startswith("app/locales/") for r in rels)
