"""CloudWatch FilterLogEvents filterPattern 构造 (纯函数).

用户在单个 stream 内按关键字/正则搜索日志正文。日志是 Fluent Bit JSON envelope,
正文在 ``log`` 字段, 所以过滤限定到 ``$.log`` 避免命中元数据 (container_name /
pod_name / host / labels)。

两种模式 (均大小写敏感 — CloudWatch filterPattern 无 ignore-case):
    keyword: 子串匹配 → ``{ $.log = "*<kw>*" }``
    regex:   正则匹配 → ``{ $.log = %<regex>% }``

正则约束 (CloudWatch 限制, 见 FilterAndPatternSyntax):
    - 不支持分组括号 ``()`` (无法定义子模式)
    - 每个 filterPattern 最多 2 个正则 (这里只用 1 个, 不会超)
"""

from __future__ import annotations

from app.core.i18n import t


class FilterPatternError(ValueError):
    """用户输入的搜索表达式非法 (如正则含不支持的括号)."""


# JSON 字符串值里对结果有特殊含义的字符; 关键字模式下转义, 避免用户输入被当通配。
# ``*`` 是通配符, ``"`` 会闭合字符串, ``\`` 是转义引导。
def _escape_keyword(kw: str) -> str:
    return kw.replace("\\", "\\\\").replace('"', '\\"').replace("*", "\\*")


def build_log_filter_pattern(*, query: str, is_regex: bool) -> str:
    """query → CloudWatch filterPattern (限定 $.log 字段)。

    query 为空 → 返回空串 (调用方视为"不按内容过滤, 仅时间窗")。
    is_regex 且含 ``(`` / ``)`` → 抛 FilterPatternError。
    """
    q = query.strip()
    if not q:
        return ""
    if is_regex:
        if "(" in q or ")" in q:
            raise FilterPatternError(t("logs.regex_group_unsupported"))
        # %regex% 包裹; 字段选择器上用正则做值匹配
        return f"{{ $.log = %{q}% }}"
    # 关键字: 子串通配, 转义用户输入里的特殊字符
    return f'{{ $.log = "*{_escape_keyword(q)}*" }}'
