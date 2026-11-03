"""get_gpu_counts / get_gpu_infos 批量查 + 去重 + 失败降级。"""
import pytest

from app.adapters.aws import ec2_instance_types as m
from app.adapters.aws.ec2_instance_types import InstanceSpec


@pytest.fixture(autouse=True)
def _reset_cache():
    m.reset_cache()
    yield
    m.reset_cache()


@pytest.mark.asyncio
async def test_batch(monkeypatch):
    async def fake_batch(types):
        assert set(types) == {"g6.12xlarge", "m5.4xlarge"}
        return {
            "g6.12xlarge": InstanceSpec(
                gpu_count=4, gpu_spec="4×L4", gpu_type="L4", vcpu=48, memory_gib=192.0
            ),
            "m5.4xlarge": InstanceSpec(
                gpu_count=0, gpu_spec=None, gpu_type=None, vcpu=16, memory_gib=64.0
            ),
        }

    monkeypatch.setattr(m, "_describe_instance_specs_batch", fake_batch)
    out = await m.get_gpu_counts(["ml.g6.12xlarge", "ml.m5.4xlarge"])
    assert out == {"ml.g6.12xlarge": 4, "ml.m5.4xlarge": 0}


@pytest.mark.asyncio
async def test_gpu_infos(monkeypatch):
    async def fake_batch(types):
        return {
            "g5.12xlarge": InstanceSpec(
                gpu_count=4, gpu_spec="4×A10G", gpu_type="A10G", vcpu=48, memory_gib=192.0
            ),
            "c5.2xlarge": InstanceSpec(
                gpu_count=0, gpu_spec=None, gpu_type=None, vcpu=8, memory_gib=16.0
            ),
        }

    monkeypatch.setattr(m, "_describe_instance_specs_batch", fake_batch)
    out = await m.get_gpu_infos(["ml.g5.12xlarge", "ml.c5.2xlarge"])
    assert out["ml.g5.12xlarge"].gpu_count == 4
    assert out["ml.g5.12xlarge"].gpu_spec == "4×A10G"
    assert out["ml.c5.2xlarge"].gpu_count == 0


@pytest.mark.asyncio
async def test_dedup_and_empty(monkeypatch):
    calls = []

    async def fake_batch(types):
        calls.append(sorted(types))
        return {
            t: InstanceSpec(
                gpu_count=0, gpu_spec=None, gpu_type=None, vcpu=16, memory_gib=64.0
            )
            for t in types
        }

    monkeypatch.setattr(m, "_describe_instance_specs_batch", fake_batch)
    out = await m.get_gpu_counts(["ml.m5.4xlarge", "ml.m5.4xlarge"])
    assert out == {"ml.m5.4xlarge": 0}
    assert calls == [["m5.4xlarge"]]
    assert await m.get_gpu_counts([]) == {}


@pytest.mark.asyncio
async def test_cache_hit_not_overwritten(monkeypatch):
    """同机型已缓存的旧值优先于本次新值 (get_or_load 命中不调 loader)。"""
    async def first(types):
        return {
            "g6.12xlarge": InstanceSpec(
                gpu_count=4, gpu_spec="4×L4", gpu_type="L4", vcpu=48, memory_gib=192.0
            )
        }

    monkeypatch.setattr(m, "_describe_instance_specs_batch", first)
    assert await m.get_gpu_counts(["ml.g6.12xlarge"]) == {"ml.g6.12xlarge": 4}

    async def changed(types):
        return {
            "g6.12xlarge": InstanceSpec(
                gpu_count=99, gpu_spec="99×L4", gpu_type="L4", vcpu=48, memory_gib=192.0
            )
        }

    monkeypatch.setattr(m, "_describe_instance_specs_batch", changed)
    assert await m.get_gpu_counts(["ml.g6.12xlarge"]) == {"ml.g6.12xlarge": 4}


@pytest.mark.asyncio
async def test_failure_degrades_zero(monkeypatch):
    async def boom(types):
        raise RuntimeError("ec2 down")

    monkeypatch.setattr(m, "_describe_instance_specs_batch", boom)
    out = await m.get_gpu_counts(["ml.g6.12xlarge"])
    assert out == {"ml.g6.12xlarge": 0}


@pytest.mark.asyncio
async def test_build_gpu_spec():
    """_build_gpu_spec 拼接格式测试。"""
    assert m._build_gpu_spec([]) is None
    assert m._build_gpu_spec([{"Count": 4, "Name": "A10G"}]) == "4×A10G"
    assert m._build_gpu_spec([{"Count": 8, "Name": "H100"}]) == "8×H100"
    # 多种 GPU (理论上 AWS 单机型只有一种, 但接口支持多个)
    assert m._build_gpu_spec([
        {"Count": 4, "Name": "A10G"},
        {"Count": 2, "Name": "T4"},
    ]) == "4×A10G + 2×T4"


@pytest.mark.asyncio
async def test_describe_uses_us_east_1(monkeypatch):
    """规格查询必须固定走 us-east-1, 与平台主区 aws_region 解耦。"""
    captured = {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def describe_instance_types(self, InstanceTypes):
            return {
                "InstanceTypes": [
                    {
                        "InstanceType": "g6.12xlarge",
                        "VCpuInfo": {"DefaultVCpus": 48},
                        "MemoryInfo": {"SizeInMiB": 196608},
                        "GpuInfo": {"Gpus": [{"Count": 4, "Name": "L4"}]},
                    }
                ]
            }

    class FakeSession:
        def client(self, svc, region_name=None):
            captured["svc"] = svc
            captured["region"] = region_name
            return FakeClient()

    monkeypatch.setattr(m.aioboto3, "Session", lambda: FakeSession())
    out = await m.get_instance_specs(["ml.g6.12xlarge"])

    assert captured["region"] == "us-east-1"
    spec = out["ml.g6.12xlarge"]
    assert spec.gpu_count == 4
    assert spec.gpu_spec == "4×L4"
    assert spec.gpu_type == "L4"
    assert spec.vcpu == 48
    assert spec.memory_gib == 192.0  # 196608 MiB / 1024


@pytest.mark.asyncio
async def test_get_instance_specs_batch(monkeypatch):
    async def fake_batch(types):
        return {
            "g6.12xlarge": InstanceSpec(gpu_count=4, gpu_spec="4×L4", gpu_type="L4", vcpu=48, memory_gib=192.0),
            "m5.4xlarge": InstanceSpec(gpu_count=0, gpu_spec=None, gpu_type=None, vcpu=16, memory_gib=64.0),
        }

    monkeypatch.setattr(m, "_describe_instance_specs_batch", fake_batch)
    out = await m.get_instance_specs(["ml.g6.12xlarge", "ml.m5.4xlarge"])
    assert out["ml.g6.12xlarge"].vcpu == 48
    assert out["ml.g6.12xlarge"].gpu_type == "L4"
    assert out["ml.m5.4xlarge"].gpu_count == 0
    assert out["ml.m5.4xlarge"].memory_gib == 64.0


@pytest.mark.asyncio
async def test_get_instance_specs_degrades(monkeypatch):
    async def boom(types):
        raise RuntimeError("ec2 down")

    monkeypatch.setattr(m, "_describe_instance_specs_batch", boom)
    out = await m.get_instance_specs(["ml.g6.12xlarge"])
    assert out["ml.g6.12xlarge"].gpu_count == 0
    assert out["ml.g6.12xlarge"].vcpu == 0
