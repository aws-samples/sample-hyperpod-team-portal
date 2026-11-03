"""pytest 全局: 测试默认请求语言设为 zh-CN。

既有用例直接调路由/编排函数 (不经 LocaleMiddleware) 并断言中文报错; 迁移到 t() 后默认语言
若是生产的 en-US, 这些断言会全变。monkeypatch 模块级 DEFAULT (非 ContextVar) 对任何线程 /
事件循环 / TestClient 都生效。要测英文或真实默认值的用例, 在测试模块里定义同名 autouse
fixture `_zh_cn_locale` 覆盖本 fixture (见 app/core/tests/test_i18n.py)。见 docs/i18n-glossary.md §0。
"""

import pytest

from app.core import i18n


@pytest.fixture(autouse=True)
def _zh_cn_locale(monkeypatch):
    monkeypatch.setattr(i18n, "DEFAULT", i18n.ZH_CN)
