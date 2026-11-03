# app/modules/logs/tests/test_filter_pattern.py
"""Logs · filterPattern 构造单测 (纯函数)."""

from __future__ import annotations

import pytest

from app.modules.logs.domain.filter_pattern import (
    FilterPatternError,
    build_log_filter_pattern,
)


def test_empty_query_returns_empty() -> None:
    assert build_log_filter_pattern(query="", is_regex=False) == ""
    assert build_log_filter_pattern(query="   ", is_regex=True) == ""


def test_keyword_wraps_json_log_wildcard() -> None:
    assert (
        build_log_filter_pattern(query="CUDA oom", is_regex=False)
        == '{ $.log = "*CUDA oom*" }'
    )


def test_keyword_escapes_special_chars() -> None:
    # * / " / \ 会破坏 filterPattern 语义, 关键字模式须转义
    out = build_log_filter_pattern(query='a*b"c\\d', is_regex=False)
    assert out == '{ $.log = "*a\\*b\\"c\\\\d*" }'


def test_regex_wraps_percent() -> None:
    assert (
        build_log_filter_pattern(query="loss=\\d+", is_regex=True)
        == "{ $.log = %loss=\\d+% }"
    )


def test_regex_rejects_parens() -> None:
    with pytest.raises(FilterPatternError):
        build_log_filter_pattern(query="(a|b)", is_regex=True)
    with pytest.raises(FilterPatternError):
        build_log_filter_pattern(query="a)b", is_regex=True)
