"""upsert_resource_if_newer 去重条件构造测试 (A2)。

去重: 首次(行不存在) OR (rv 更新 且 phase/started_at/ended_at/priority_class 任一变) 才写。
不比 message、不比 rv 值本身做去重 (2026-06-09 确定, 真集群实证)。
"""
from app.repositories.resource_index import _DEDUP_FIELDS, _build_dedup_condition


def test_dedup_fields():
    # endpoint_url 加入去重 (推理 endpoint InService 后 url 落库, 见 resource_index 注释)
    # kueue_status 加入去重: 它已归 informer 状态字段, 三态变化需触发落库 (KS-4)。
    assert _DEDUP_FIELDS == (
        "phase", "started_at", "ended_at", "priority_class", "endpoint_url",
        "status_detail", "kueue_status",
    )


def test_dedup_condition_compares_four_fields():
    cond, names, values = _build_dedup_condition(
        resource_version=100,
        md={
            "phase": "Running",
            "started_at": "t1",
            "ended_at": None,
            "priority_class": "training-default",
            "last_condition_message": "noise",
        },
    )
    # 首次 (行不存在) 放行
    assert "attribute_not_exists(workspace_id)" in cond
    # rv 更新才写 (防回退)
    assert "#md.#rv < :rv" in cond
    # 四个去重字段的新值都在 expression_values
    assert values[":phase"] == "Running"
    assert values[":started_at"] == "t1"
    assert values[":ended_at"] is None
    assert values[":priority_class"] == "training-default"
    # 不比 message
    assert ":last_condition_message" not in values
    assert "last_condition_message" not in cond
    # rv 只用于"更新判断", 不作为内容去重字段
    assert values[":rv"] == 100


def test_dedup_condition_handles_none_values():
    """None 字段 (ended_at/priority_class) 也能比对 (DDB 存 NULL)。"""
    cond, names, values = _build_dedup_condition(
        resource_version=100,
        md={"phase": "Pending", "started_at": None, "ended_at": None,
            "priority_class": None},
    )
    assert values[":started_at"] is None
    assert values[":ended_at"] is None
    assert values[":priority_class"] is None
    # 每个去重字段都有 attribute_not_exists OR <> 子句 (处理 DDB 现有行缺该字段)
    for f in _DEDUP_FIELDS:
        assert f"attribute_not_exists(#md.#{f})" in cond
        assert f"#md.#{f} <> :{f}" in cond
