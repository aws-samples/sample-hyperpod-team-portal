from app.core.security import get_current_user, require_admin
from app.modules.fsx_quota.api.monitoring_router import (
    _range_to_window,
    fsx_monitoring_router,
)
from app.modules.fsx_quota.api.router import fsx_quota_router


def test_quota_router_requires_admin():
    # 配额端点 (建/改/读目录) 必须走超管闸门 —— 校验 router 级依赖挂了 require_admin,
    # 防止有人误删依赖导致端点对普通用户裸奔。
    deps = [d.dependency for d in fsx_quota_router.dependencies]
    assert require_admin in deps


def test_monitoring_router_any_user():
    # 监控端点所有登录用户可看 —— 挂 get_current_user (非 require_admin),
    # 与工作空间无关。
    deps = [d.dependency for d in fsx_monitoring_router.dependencies]
    assert get_current_user in deps
    assert require_admin not in deps


def test_range_to_window_1h():
    start, end, period = _range_to_window("1h")
    assert period == 60
    assert (end - start).total_seconds() == 3600


def test_range_to_window_6h():
    _, _, period = _range_to_window("6h")
    assert period == 300


def test_range_to_window_24h():
    start, end, period = _range_to_window("24h")
    assert (end - start).total_seconds() == 86400
    assert period == 300


def test_range_to_window_default():
    # 未知 range 回落 1h
    _, _, period = _range_to_window("bogus")
    assert period == 60
