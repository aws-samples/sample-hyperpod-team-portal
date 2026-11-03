"""后端中英文案表一致: 文件集合 / key 集合 / {占位符} 集合相同, en-US 不含中文。"""
import re
from string import Formatter

from app.core import i18n

# 与守门脚本同一宽范围: CJK 符号标点 / 扩展 A / 基本汉字 / 全角半角形式
_CJK = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]")


def _fields(text: str) -> list[str]:
    return sorted({f for _, f, _, _ in Formatter().parse(text) if f})


def test_same_files():
    zh = {p.name for p in (i18n.LOCALES_DIR / "zh-CN").glob("*.json")}
    en = {p.name for p in (i18n.LOCALES_DIR / "en-US").glob("*.json")}
    assert zh == en


def test_same_keys():
    zh, en = i18n.load_catalog("zh-CN"), i18n.load_catalog("en-US")
    assert sorted(zh.keys() - en.keys()) == []
    assert sorted(en.keys() - zh.keys()) == []


def test_same_placeholders():
    zh, en = i18n.load_catalog("zh-CN"), i18n.load_catalog("en-US")
    bad = [k for k in zh if k in en and _fields(zh[k]) != _fields(en[k])]
    assert bad == []


def test_en_us_has_no_cjk():
    assert [k for k, v in i18n.load_catalog("en-US").items() if _CJK.search(v)] == []


def test_catalogs_validate():
    # 启动期校验必须在真实文案表上通过
    i18n.validate_catalogs()


def test_conftest_default_is_zh_cn():
    # 本文件不覆盖 _zh_cn_locale, 故 conftest 把 DEFAULT 打成 zh-CN
    assert i18n.get_locale() == "zh-CN"
