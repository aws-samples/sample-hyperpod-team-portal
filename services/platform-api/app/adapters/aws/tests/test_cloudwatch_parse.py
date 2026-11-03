from datetime import UTC, datetime

from app.adapters.aws.cloudwatch import (
    build_metric_queries,
    parse_metric_results,
    resolve_query_specs,
)


# list_metrics 的仿真返回 (含额外维度组合), 覆盖 FileServer / StorageTargetId /
# OST-vs-MDT 前缀选择。
_LISTED = [
    {"MetricName": "NetworkThroughputUtilization",
     "Dimensions": [{"Name": "FileSystemId", "Value": "fs-abc"},
                    {"Name": "FileServer", "Value": "OSS0000"}]},
    {"MetricName": "FileServerDiskThroughputUtilization",
     "Dimensions": [{"Name": "FileSystemId", "Value": "fs-abc"},
                    {"Name": "FileServer", "Value": "OSS0000"}]},
    {"MetricName": "DiskIopsUtilization",
     "Dimensions": [{"Name": "FileSystemId", "Value": "fs-abc"},
                    {"Name": "StorageTargetId", "Value": "MDT0000"}]},
    {"MetricName": "DiskIopsUtilization",
     "Dimensions": [{"Name": "FileSystemId", "Value": "fs-abc"},
                    {"Name": "StorageTargetId", "Value": "OST0000"}]},
    {"MetricName": "CPUUtilization",
     "Dimensions": [{"Name": "FileSystemId", "Value": "fs-abc"},
                    {"Name": "FileServer", "Value": "MDS0000"}]},
]


def test_resolve_query_specs_dimensions():
    resolved = resolve_query_specs("fs-abc", _LISTED)
    by_key = {r["key"]: r for r in resolved}
    # Storage 两条: 仅 FileSystemId 维
    assert by_key["FreeDataStorageCapacity"]["dimensions"] == [
        {"Name": "FileSystemId", "Value": "fs-abc"}
    ]
    assert by_key["StorageCapacityUtilization"]["dimensions"] == [
        {"Name": "FileSystemId", "Value": "fs-abc"}
    ]
    # Network throughput: 带 FileServer=OSS0000
    net_dims = by_key["NetworkThroughputUtilization"]["dimensions"]
    assert {"Name": "FileServer", "Value": "OSS0000"} in net_dims
    # Disk IOPS: value_prefix=OST → 选 OST0000, 排除 MDT0000
    iops_dims = by_key["DiskIopsUtilization"]["dimensions"]
    assert {"Name": "StorageTargetId", "Value": "OST0000"} in iops_dims
    assert {"Name": "StorageTargetId", "Value": "MDT0000"} not in iops_dims
    # CPU: FileServer=MDS0000
    cpu_dims = by_key["CPUUtilization"]["dimensions"]
    assert {"Name": "FileServer", "Value": "MDS0000"} in cpu_dims
    # id 全小写开头 (get_metric_data Id 规则)
    assert all(r["id"].startswith("m") for r in resolved)


def test_resolve_skips_missing_metric():
    # list_metrics 只返 Storage 两条 → 带额外维度的都探不到, 跳过
    listed = [{"MetricName": "StorageCapacityUtilization",
               "Dimensions": [{"Name": "FileSystemId", "Value": "fs-abc"}]}]
    resolved = resolve_query_specs("fs-abc", listed)
    keys = {r["key"] for r in resolved}
    # 仅 FileSystemId 维的两条恒在; 带额外维度的因探不到而跳过
    assert "StorageCapacityUtilization" in keys
    assert "FreeDataStorageCapacity" in keys
    assert "DiskIopsUtilization" not in keys
    assert "CPUUtilization" not in keys


def test_build_metric_queries_from_resolved():
    resolved = resolve_query_specs("fs-abc", _LISTED)
    q = build_metric_queries(resolved, period=300)
    assert len(q) == len(resolved)
    assert all("Expression" not in item for item in q)  # 无 metric math
    for item in q:
        assert item["Id"].startswith("m")
        assert item["MetricStat"]["Period"] == 300
        assert item["MetricStat"]["Metric"]["Namespace"] == "AWS/FSx"


def test_parse_results_maps_id_to_key():
    t0 = datetime(2026, 7, 21, 5, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 7, 21, 5, 5, 0, tzinfo=UTC)
    id_to_key = {"m0": "FreeDataStorageCapacity", "m4": "DiskIopsUtilization"}
    raw = [
        {"Id": "m0", "Timestamps": [t0, t1], "Values": [1.2e12, 1.1e12]},
        {"Id": "m4", "Timestamps": [t0], "Values": [3.5]},
    ]
    out = parse_metric_results(raw, id_to_key)
    assert out["FreeDataStorageCapacity"] == [
        (t0.isoformat(), 1.2e12),
        (t1.isoformat(), 1.1e12),
    ]
    assert out["DiskIopsUtilization"] == [(t0.isoformat(), 3.5)]
    for series in out.values():
        for ts, val in series:
            assert isinstance(ts, str)
            assert isinstance(val, float)
