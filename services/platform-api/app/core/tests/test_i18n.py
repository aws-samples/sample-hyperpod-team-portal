"""app.core.i18n: 严格语言判定 / ContextVar / 文案表加载 / t() 回落。"""
import json
import pytest
from structlog.testing import capture_logs

from app.core import i18n


@pytest.fixture(autouse=True)
def _zh_cn_locale():
    """覆盖 conftest 同名 autouse fixture: 本文件测真实 DEFAULT (en-US)。"""
    yield


@pytest.fixture
def catalogs(tmp_path, monkeypatch):
    def write(locale: str, name: str, data: dict) -> None:
        d = tmp_path / locale
        d.mkdir(exist_ok=True)
        (d / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(i18n, "LOCALES_DIR", tmp_path)
    i18n.load_catalog.cache_clear()
    yield write
    i18n.load_catalog.cache_clear()


@pytest.mark.parametrize(
    "header,query,expected",
    [
        (None, None, "en-US"),
        ("", None, "en-US"),
        ("zh-CN", None, "zh-CN"),
        ("zh-CN,zh;q=0.9,en;q=0.8", None, "zh-CN"),
        ("zh-CN;q=0.9", None, "zh-CN"),
        ("zh", None, "en-US"),
        ("zh-TW", None, "en-US"),
        ("zh-cn", None, "en-US"),
        ("en-GB,zh-CN;q=0.9", None, "en-US"),
        ("fr-FR", None, "en-US"),
        ("en-US", "zh-CN", "zh-CN"),
        ("zh-CN", "en-US", "en-US"),
        ("zh-CN", "", "zh-CN"),
        (None, "ja", "en-US"),
    ],
)
def test_resolve_locale_strict(header, query, expected):
    assert i18n.resolve_locale(header, query) == expected


def test_get_locale_defaults_to_en_us():
    assert i18n.get_locale() == "en-US"


def test_set_and_reset_locale():
    token = i18n.set_locale("zh-CN")
    assert i18n.get_locale() == "zh-CN"
    i18n.reset_locale(token)
    assert i18n.get_locale() == "en-US"


def test_set_locale_unsupported_becomes_en_us():
    token = i18n.set_locale("fr-FR")
    try:
        assert i18n.get_locale() == "en-US"
    finally:
        i18n.reset_locale(token)


def test_t_uses_current_locale_and_formats(catalogs):
    catalogs("zh-CN", "demo.json", {"demo.hello": "你好 {name}"})
    catalogs("en-US", "demo.json", {"demo.hello": "Hello {name}"})
    assert i18n.t("demo.hello", name="Bob") == "Hello Bob"
    token = i18n.set_locale("zh-CN")
    try:
        assert i18n.t("demo.hello", name="Bob") == "你好 Bob"
    finally:
        i18n.reset_locale(token)


def test_t_falls_back_to_en_us(catalogs):
    catalogs("zh-CN", "demo.json", {})
    catalogs("en-US", "demo.json", {"demo.only_en": "English only"})
    token = i18n.set_locale("zh-CN")
    try:
        assert i18n.t("demo.only_en") == "English only"
    finally:
        i18n.reset_locale(token)


def test_t_missing_key_returns_key_and_warns(catalogs):
    catalogs("zh-CN", "demo.json", {})
    catalogs("en-US", "demo.json", {})
    with capture_logs() as logs:
        assert i18n.t("demo.nope") == "demo.nope"
    assert any(e["event"] == "i18n_missing_key" and e["key"] == "demo.nope" for e in logs)


def test_t_resolves_escaped_braces(catalogs):
    catalogs("zh-CN", "demo.json", {"demo.json": '示例 {{"a": 1}}'})
    catalogs("en-US", "demo.json", {"demo.json": 'example {{"a": 1}}'})
    assert i18n.t("demo.json") == 'example {"a": 1}'


def test_load_catalog_merges_files(catalogs):
    catalogs("en-US", "a.json", {"a.x": "1"})
    catalogs("en-US", "b.json", {"b.y": "2"})
    assert i18n.load_catalog("en-US") == {"a.x": "1", "b.y": "2"}


def test_load_catalog_rejects_duplicate_keys(catalogs):
    catalogs("en-US", "a.json", {"dup.k": "1"})
    catalogs("en-US", "b.json", {"dup.k": "2"})
    with pytest.raises(ValueError, match="duplicate"):
        i18n.load_catalog("en-US")


def test_has(catalogs):
    catalogs("zh-CN", "demo.json", {"demo.k": "值"})
    catalogs("en-US", "demo.json", {"demo.k": "v"})
    assert i18n.has("demo.k")
    assert i18n.has("demo.k", "zh-CN")
    assert not i18n.has("demo.missing")


@pytest.mark.parametrize(
    "template",
    ["hi {name}", "bad { brace", "pos {0}"],
)
def test_t_bad_template_never_raises(catalogs, template):
    catalogs("en-US", "demo.json", {"demo.p": template})
    with capture_logs() as logs:
        assert i18n.t("demo.p") == template
    assert any(e["event"] == "i18n_format_failed" and e["key"] == "demo.p" for e in logs)


def test_t_key_is_positional_only(catalogs):
    catalogs("en-US", "demo.json", {"demo.k": "label {key} bad"})
    assert i18n.t("demo.k", key="foo") == "label foo bad"


def test_validate_catalogs_ok(catalogs):
    catalogs("zh-CN", "demo.json", {"demo.k": "值"})
    catalogs("en-US", "demo.json", {"demo.k": "v"})
    i18n.validate_catalogs()


def test_validate_catalogs_allows_empty(catalogs):
    catalogs("zh-CN", "demo.json", {})
    catalogs("en-US", "demo.json", {})
    i18n.validate_catalogs()


def test_validate_catalogs_missing_dir(catalogs):
    catalogs("en-US", "demo.json", {})
    with pytest.raises(RuntimeError, match="zh-CN"):
        i18n.validate_catalogs()


def test_validate_catalogs_non_str_value(catalogs):
    catalogs("zh-CN", "demo.json", {})
    catalogs("en-US", "bad_file.json", {"a.b": 1})
    with pytest.raises(RuntimeError, match="bad_file.json"):
        i18n.validate_catalogs()


def test_validate_catalogs_non_object(catalogs):
    catalogs("zh-CN", "demo.json", {})
    catalogs("en-US", "listy.json", ["x"])
    with pytest.raises(RuntimeError, match="listy.json"):
        i18n.validate_catalogs()


def test_validate_catalogs_duplicate_keys(catalogs):
    catalogs("zh-CN", "demo.json", {})
    catalogs("en-US", "a.json", {"dup.k": "1"})
    catalogs("en-US", "b.json", {"dup.k": "2"})
    with pytest.raises(ValueError, match="duplicate"):
        i18n.validate_catalogs()
