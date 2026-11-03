"""Auth · 骨架烟测.

M1 阶段 auth 只有目录结构, 没有实际代码. 这里只确认 import 不炸,
Phase 3+ 加 token/oidc 实现后这里会补充真实测试.
"""

from __future__ import annotations


def test_auth_package_importable() -> None:
    import app.modules.auth  # noqa: F401
    import app.modules.auth.api  # noqa: F401
    import app.modules.auth.domain  # noqa: F401
    import app.modules.auth.orchestration  # noqa: F401
    import app.modules.auth.persistence  # noqa: F401
    import app.modules.auth.response  # noqa: F401
