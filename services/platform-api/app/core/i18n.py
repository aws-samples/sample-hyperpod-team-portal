"""运行时中英双语文案 (贡献者指南见 docs/i18n-glossary.md §0)。

- 语言集 zh-CN / en-US。严格规则: 恰好 "zh-CN" 才是中文, 其余一律 en-US; 未传走 DEFAULT。
- 当前请求语言存 ContextVar, 由 LocaleMiddleware 每请求设置; 深层代码直接 t() 即可。
- 文案表: app/locales/<locale>/*.json (扁平 key, 自带模块前缀), 首次使用时加载并缓存。
- t() 必须在请求处理期间调用 (模块级常量里调用会冻结在 import 时的语言)。
"""

from __future__ import annotations

import json
from contextvars import ContextVar, Token
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

ZH_CN = "zh-CN"
EN_US = "en-US"
SUPPORTED: tuple[str, ...] = (ZH_CN, EN_US)
# 无 ?lang= / Accept-Language 时的语言。函数内按名读取 (非默认参数), 测试可 monkeypatch。
DEFAULT = EN_US

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"

_current: ContextVar[str | None] = ContextVar("platform_api_locale", default=None)
logger = get_logger(__name__)


def _strict(tag: str) -> str:
    return ZH_CN if tag == ZH_CN else EN_US


def resolve_locale(accept_language: str | None, query_lang: str | None = None) -> str:
    """?lang= 优先 (EventSource / WebSocket 设不了头), 其次 Accept-Language 第一个语言标签。"""
    if query_lang is not None and query_lang.strip():
        return _strict(query_lang.strip())
    if accept_language is None or not accept_language.strip():
        return DEFAULT
    first = accept_language.split(",", 1)[0].split(";", 1)[0].strip()
    return _strict(first)


def get_locale() -> str:
    return _current.get() or DEFAULT


def set_locale(locale: str) -> Token[str | None]:
    # 不支持的值归 en-US (而非 DEFAULT), 与 resolve_locale 一致
    return _current.set(locale if locale in SUPPORTED else EN_US)


def reset_locale(token: Token[str | None]) -> None:
    _current.reset(token)


@lru_cache(maxsize=None)
def load_catalog(locale: str) -> dict[str, str]:
    merged: dict[str, str] = {}
    for f in sorted((LOCALES_DIR / locale).glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        dup = merged.keys() & data.keys()
        if dup:
            raise ValueError(f"duplicate i18n keys in {locale}/{f.name}: {sorted(dup)[:5]}")
        merged.update(data)
    return merged


def has(key: str, /, locale: str | None = None) -> bool:
    return key in load_catalog(locale or get_locale())


def validate_catalogs() -> None:
    """启动期校验 (由 app lifespan 调用): 目录齐全, 每个 json 是 str->str 对象, 无重复 key。"""
    for locale in SUPPORTED:
        d = LOCALES_DIR / locale
        if not d.is_dir():
            raise RuntimeError(f"i18n locale dir missing: {d}")
        for f in sorted(d.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except ValueError as e:
                raise RuntimeError(f"i18n catalog {locale}/{f.name} is not valid JSON: {e}") from e
            if not isinstance(data, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in data.items()
            ):
                raise RuntimeError(f"i18n catalog {locale}/{f.name} must be a JSON object of str -> str")
        load_catalog(locale)


def t(key: str, /, **params: Any) -> str:
    """按当前请求语言取文案并 str.format(**params); 缺失回落 en-US, 再缺返回 key 本身 (不抛)。

    模板与参数不匹配时同样不抛 (t() 常在错误路径里调用): 记 error 并返回未格式化原文。
    """
    loc = get_locale()
    text = load_catalog(loc).get(key)
    if text is None and loc != EN_US:
        text = load_catalog(EN_US).get(key)
    if text is None:
        logger.warning("i18n_missing_key", key=key, locale=loc)
        return key
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        logger.error("i18n_format_failed", key=key, locale=loc, exc_info=True)
        return text
