"""default_priority_class 解析函数测试."""
from __future__ import annotations

import pytest

from app.core import priority_defaults as pd
from app.core.config import get_settings


def test_known_types_return_configured_defaults():
    s = get_settings()
    assert pd.default_priority_class("train") == s.priority_default_train
    assert pd.default_priority_class("inference") == s.priority_default_inference
    assert pd.default_priority_class("dynamo") == s.priority_default_dynamo
    assert pd.default_priority_class("llmd") == s.priority_default_llmd
    assert pd.default_priority_class("rayjob") == s.priority_default_rayjob
    assert pd.default_priority_class("devinstance") == s.priority_default_devinstance


def test_unknown_type_returns_fallback():
    s = get_settings()
    assert pd.default_priority_class("something-new") == s.priority_default_fallback


def test_empty_type_returns_fallback():
    s = get_settings()
    assert pd.default_priority_class("") == s.priority_default_fallback


def test_empty_configured_value_falls_back(monkeypatch):
    # 某类的 setting 被配成空串 → 退到 fallback (不给 CR 打空 label)
    from app.core import config as cfg

    s = cfg.get_settings()
    monkeypatch.setattr(s, "priority_default_train", "")
    assert pd.default_priority_class("train") == s.priority_default_fallback
