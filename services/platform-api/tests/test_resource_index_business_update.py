"""update_business_fields 部分更新业务字段测试 (A4 bugfix)。

背景: 开发机接入 informer 后, DDB 有两个写入方:
  - informer: 部分更新状态字段 (phase/started_at/ended_at/priority_class/k8s_resource_version)
  - platform-api (stop/start/改名/SSM): 写业务字段
原 crud.update 用 upsert_resource 整行 PutItem 覆盖整个 metadata, 会:
  ① 用 row 里的旧 phase 覆盖 informer 刚写的新 phase
  ② metadata 不含 k8s_resource_version → 把 informer 的 rv 冲成 null
本方法让 platform-api 只 SET 自己的业务字段 (metadata.<子字段> 部分更新),
绝不碰状态字段 → 与 informer 互不覆盖。
"""
from app.repositories.resource_index import (
    _STATUS_FIELDS,
    _build_business_update_expr,
)


def test_business_update_set_and_remove():
    # 非 None → SET; None → REMOVE 子字段 (清空=删字段, 同原整行put"None不写=消失"语义)
    update_expr, names, values = _build_business_update_expr(
        {"desired_status": "Stopped", "ssm_managed_id": None, "stopped_at": "t1"}
    )
    # SET 段含非 None 字段
    assert "SET " in update_expr
    assert "#md.#desired_status = :desired_status" in update_expr
    assert "#md.#stopped_at = :stopped_at" in update_expr
    assert values[":desired_status"] == "Stopped"
    # REMOVE 段含 None 字段 (清空 SSM)
    assert "REMOVE " in update_expr
    assert "#md.#ssm_managed_id" in update_expr
    assert ":ssm_managed_id" not in values  # REMOVE 不需要值
    assert names["#md"] == "metadata"


def test_business_update_only_remove():
    # 全是 None → 只有 REMOVE 段, 无 SET
    update_expr, names, values = _build_business_update_expr({"ssm_managed_id": None})
    assert update_expr.startswith("REMOVE ")
    assert "SET " not in update_expr
    assert values == {}


def test_business_update_rejects_status_fields():
    """绝不允许写状态字段 (那是 informer 的领域) — 传入则抛错, 防回归。"""
    import pytest
    for f in _STATUS_FIELDS:
        with pytest.raises(ValueError, match="status field"):
            _build_business_update_expr({f: "x"})


def test_business_update_empty_is_noop_marker():
    # 空业务字段 → 返回 None (调用方据此跳过, 不发空 UpdateExpression)
    result = _build_business_update_expr({})
    assert result is None
