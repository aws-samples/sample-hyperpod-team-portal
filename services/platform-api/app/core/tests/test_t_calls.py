"""静态扫描 app/ 下所有 t("<字面 key>", ...) 调用:

- key 必须同时存在于 zh-CN / en-US 文案表;
- 调用的关键字参数名集合必须等于两种语言模板里的 {占位符} 集合。

t() 本身运行期不抛 (缺 key 返 key, 参数不匹配返原文), 这里把这类错误挡在 CI。
首参不是字符串字面量的调用 (动态 key, 由各模块自己的测试覆盖) 与带 **kwargs 的调用跳过。
"""
import ast
from pathlib import Path
from string import Formatter

from app.core import i18n

APP = Path(__file__).resolve().parents[2]  # services/platform-api/app


def _fields(text: str) -> set[str]:
    return {f for _, f, _, _ in Formatter().parse(text) if f}


def _source_files():
    for p in sorted(APP.rglob("*.py")):
        if "tests" in p.relative_to(APP).parts or "__pycache__" in p.parts:
            continue
        yield p


def _t_calls():
    for p in _source_files():
        tree = ast.parse(p.read_text(encoding="utf-8"), str(p))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "t"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                continue
            if any(kw.arg is None for kw in node.keywords):  # **kwargs
                continue
            yield p.relative_to(APP.parent), node.lineno, node.args[0].value, {
                kw.arg for kw in node.keywords
            }


def test_t_calls_match_catalogs():
    catalogs = {loc: i18n.load_catalog(loc) for loc in i18n.SUPPORTED}
    problems: list[str] = []
    n = 0
    for path, line, key, kwargs in _t_calls():
        n += 1
        for loc, cat in catalogs.items():
            if key not in cat:
                problems.append(f"{path}:{line} {key!r} missing in {loc}")
                continue
            want = _fields(cat[key])
            if kwargs != want:
                problems.append(
                    f"{path}:{line} {key!r} [{loc}] placeholders {sorted(want)} != kwargs {sorted(kwargs)}"
                )
    assert n > 0, "scanner found no t() calls; scan logic is broken"
    assert problems == [], "\n" + "\n".join(problems)
