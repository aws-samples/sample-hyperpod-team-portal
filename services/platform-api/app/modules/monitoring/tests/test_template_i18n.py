"""监控模板: 展示文案全部来自文案表, 按请求语言填充; 分组带稳定 slug。"""
from app.core import i18n
from app.modules.monitoring.domain import promql
from app.modules.monitoring.domain.template_subst import _group_of, localize_template, subst_template

ALL = [tpl for name in dir(promql) if name.endswith("_TEMPLATES") for tpl in getattr(promql, name)]


def test_raw_templates_carry_no_display_text():
    # 原始模板只含结构字段: 展示文案 / 分组展示名都由 localize_template 按语言填 (分组标识走 group_key)
    assert [
        tpl.key for tpl in ALL if tpl.title != "" or tpl.description is not None or tpl.group is not None
    ] == []


def test_every_template_has_title_in_both_locales():
    for loc in i18n.SUPPORTED:
        missing = [tpl.key for tpl in ALL if not i18n.has(f"monitoring.tpl.{tpl.key}.title", loc)]
        assert missing == [], (loc, missing[:10])


def test_every_group_slug_has_name_in_both_locales():
    slugs = {tpl.group_key or _group_of(tpl) for tpl in ALL}
    for loc in i18n.SUPPORTED:
        assert sorted(s for s in slugs if not i18n.has(f"monitoring.group.{s}", loc)) == []


def _render(locale: str):
    token = i18n.set_locale(locale)
    try:
        return subst_template(promql.TRAINING_TEMPLATES[0], namespace="ns", pod_regex="p-.*")
    finally:
        i18n.reset_locale(token)


def test_subst_localizes_by_current_locale():
    zh, en = _render(i18n.ZH_CN), _render(i18n.EN_US)
    assert promql.TRAINING_TEMPLATES[0].key == "job_gpu_util_avg"
    assert zh.title == "GPU 平均利用率"
    assert en.title == i18n.load_catalog("en-US")["monitoring.tpl.job_gpu_util_avg.title"]
    assert zh.description and en.description and zh.description != en.description
    assert zh.group_key == en.group_key == "gpu"
    assert zh.group == en.group == "GPU"


def test_chinese_units_come_from_catalog():
    # 原中文单位 (核 / 卡 / 次) 进文案表按语言填; 源码里只留英文兜底, 其余单位是语言无关符号原样返回
    by_key = {tpl.key: tpl for tpl in promql.RAY_ENGINE_TEMPLATES}
    for loc, want in ((i18n.ZH_CN, "核"), (i18n.EN_US, "cores")):
        token = i18n.set_locale(loc)
        try:
            assert subst_template(by_key["ray_cpu_used"]).unit == want
            assert subst_template(by_key["ray_object_store_used"]).unit == "bytes"
        finally:
            i18n.reset_locale(token)


def test_localize_is_idempotent():
    # 显式 group_key (Ray) 与规则推导 (GPU) 两类; 二次本地化不得改变结果 (slug 来自 group_key 而非展示名)
    by_key = {tpl.key: tpl for tpl in ALL}
    for loc in i18n.SUPPORTED:
        token = i18n.set_locale(loc)
        try:
            for key in ("ray_cpu_used", "gpu_card_temp"):
                once = localize_template(by_key[key])
                assert localize_template(once) == once, (loc, key)
            ray = localize_template(by_key["ray_cpu_used"])
            assert ray.group_key == "ray_resources"
            assert ray.group == i18n.load_catalog(loc)["monitoring.group.ray_resources"]
        finally:
            i18n.reset_locale(token)


def test_catalog_values_have_no_braces():
    # t() 总会 str.format(): 文案里的字面 { } 会被当占位符 (渲染出错或记 error), 监控文案不允许出现
    for loc in i18n.SUPPORTED:
        bad = [
            k for k, v in i18n.load_catalog(loc).items()
            if k.startswith("monitoring.") and ("{" in v or "}" in v)
        ]
        assert bad == [], (loc, bad[:10])
