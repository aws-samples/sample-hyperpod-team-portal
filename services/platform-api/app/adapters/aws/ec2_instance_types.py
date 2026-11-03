"""EC2 DescribeInstanceTypes — 查机型完整规格 (GPU 卡数/型号 + vCPU + 内存).

用途: 判断一个 SageMaker instance group 是 CPU 还是 GPU —— 不能靠 IG 名/family
前缀猜, 必须查机型真实 GPU 数 (GpuInfo.Gpus[].Count)。除 GPU 卡数外还返回
gpu_spec 描述 (如 "4×A10G")、gpu_type (如 "L4")、vCPU 核数与内存 (GiB), 供前端
机型选择器展示与配额换算。

注: SageMaker 机型名带 `ml.` 前缀 (ml.g6.12xlarge), EC2 API 用裸名 (g6.12xlarge),
查询时自动剥前缀。机型规格物理固定 → 长 TTL 缓存 (1h) 避免反复调 EC2。
规格查询固定走 us-east-1 (见 INSTANCE_SPEC_REGION) —— 机型规格全球一致, 但小区/
新区可能未收录某机型致 InvalidInstanceType, 故与平台部署主区 settings.aws_region
解耦。需 IAM: ec2:DescribeInstanceTypes。
"""

from __future__ import annotations

from dataclasses import dataclass

import aioboto3

from app.adapters.aws._ttl_cache import TtlCache
from app.core.logging import get_logger

logger = get_logger(__name__)


INSTANCE_SPEC_REGION = "us-east-1"
"""机型规格查询固定区域。

机型规格 (vCPU/内存/GPU) 全球一致, 但 EC2 DescribeInstanceTypes 受"该区域是否
上架该机型"门控 —— 小区/新区可能对个别账户特批了机型却未收录进目录 →
InvalidInstanceType。故规格查询固定走机型最全的主区 us-east-1, 与平台部署主区
settings.aws_region (管 S3/FSx/EKS/ComputeQuota) 解耦。
"""


@dataclass(frozen=True, slots=True)
class InstanceSpec:
    """单机型规格 (物理固定, 可长期缓存)。"""

    gpu_count: int          # 每实例 GPU/加速卡总数 (0 = CPU 机型)
    gpu_spec: str | None    # 如 "4×L4", CPU 机型为 None
    gpu_type: str | None    # 如 "L4" / "H100" / "A10G", CPU 机型为 None
    vcpu: int               # 每实例 vCPU 核数
    memory_gib: float       # 每实例内存 GiB

    # 向后兼容别名 (旧调用方仍用 .count / .spec)
    @property
    def count(self) -> int:
        return self.gpu_count

    @property
    def spec(self) -> str | None:
        return self.gpu_spec


# 机型规格物理固定, 缓存久点 (1h).
_cache: TtlCache[InstanceSpec] | None = None


def _get_cache() -> TtlCache[InstanceSpec]:
    global _cache
    if _cache is None:
        _cache = TtlCache[InstanceSpec](ttl_seconds=3600.0)
    return _cache


def reset_cache() -> None:
    """测试用."""
    global _cache
    _cache = None


def _strip_ml_prefix(instance_type: str) -> str:
    """SageMaker `ml.g6.12xlarge` → EC2 `g6.12xlarge`."""
    return instance_type[3:] if instance_type.startswith("ml.") else instance_type


def _build_gpu_spec(gpus: list[dict]) -> str | None:
    """从 GpuInfo.Gpus[] 构建如 "4×A10G" 的描述, 无 GPU 返回 None."""
    if not gpus:
        return None
    parts: list[str] = []
    for g in gpus:
        count = int(g.get("Count", 0))
        name = g.get("Name", "")
        if count > 0 and name:
            parts.append(f"{count}×{name}")
    return " + ".join(parts) if parts else None


def _first_gpu_name(gpus: list[dict]) -> str | None:
    """取首个有卡的 GPU 型号名 (如 'L4'), 无 GPU 返回 None。"""
    for g in gpus:
        if int(g.get("Count", 0)) > 0 and g.get("Name"):
            return g["Name"]
    return None


def _parse_instance_spec(info: dict) -> InstanceSpec:
    """从单个 InstanceType 响应提取完整规格。

    已知限制 (2026-07, 暂不支持): 只统计 GpuInfo.Gpus[].Count。Trainium/Inferentia
    的加速器在 EC2 响应的 NeuronInfo.NeuronDevices[] 下 (GpuInfo 为 null), 故 trn1/
    inf* 机型 gpu_count=0 → 归 CPU 池、accelerators=0、不进 GPU 池的 nodeAffinity
    (list_workspace_pool_instance_types 按 pool 筛选)。当前环境不用 Trainium; 若将来
    启用, 需在此并入 NeuronInfo.NeuronDevices[].Count 并给 gpu_type 取 Neuron 型号。
    """
    gpu_info = info.get("GpuInfo") or {}
    gpus = gpu_info.get("Gpus") or []
    gpu_count = sum(int(g.get("Count", 0)) for g in gpus)
    vcpu = int((info.get("VCpuInfo") or {}).get("DefaultVCpus") or 0)
    mem_mib = int((info.get("MemoryInfo") or {}).get("SizeInMiB") or 0)
    return InstanceSpec(
        gpu_count=gpu_count,
        gpu_spec=_build_gpu_spec(gpus),
        gpu_type=_first_gpu_name(gpus),
        vcpu=vcpu,
        memory_gib=round(mem_mib / 1024, 1),
    )


async def _describe_instance_spec(ec2_instance_type: str) -> InstanceSpec:
    session = aioboto3.Session()
    async with session.client("ec2", region_name=INSTANCE_SPEC_REGION) as client:
        resp = await client.describe_instance_types(
            InstanceTypes=[ec2_instance_type]
        )
    infos = resp.get("InstanceTypes") or []
    if not infos:
        return InstanceSpec(gpu_count=0, gpu_spec=None, gpu_type=None, vcpu=0, memory_gib=0.0)
    return _parse_instance_spec(infos[0])


async def get_gpu_count(instance_type: str) -> int:
    """返回该 SageMaker 机型每实例 GPU 卡数 (0 = CPU 机型)。

    查不到 / EC2 报错 → 返回 0 (按 CPU 处理, 不阻断开发机创建; 软优先失效降级到
    无 affinity, 安全方向)。
    """
    if not instance_type:
        return 0
    ec2_type = _strip_ml_prefix(instance_type)
    try:
        info = await _get_cache().get_or_load(
            ec2_type, lambda: _describe_instance_spec(ec2_type)
        )
        return info.count
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ec2.describe_instance_types_fail",
            instance_type=instance_type,
            err=str(exc),
        )
        return 0


async def _describe_instance_specs_batch(ec2_types: list[str]) -> dict[str, InstanceSpec]:
    """一次 describe_instance_types 查多个裸名机型 -> {裸名: InstanceSpec}。

    注: EC2 DescribeInstanceTypes 单次 InstanceTypes 上限 100; 且列表里任一
    无效机型名会让整批调用失败 (一坏全坏)。当前调用方是单集群机型 (个位到几十,
    来自真集群必为合法机型), 两风险均不触及; 若未来传入机型数可能超 100 或含用户
    自由输入, 需在此分批 + 容错单个坏名。
    """
    if not ec2_types:
        return {}
    session = aioboto3.Session()
    async with session.client("ec2", region_name=INSTANCE_SPEC_REGION) as client:
        resp = await client.describe_instance_types(InstanceTypes=ec2_types)
    out: dict[str, InstanceSpec] = {}
    for info in resp.get("InstanceTypes") or []:
        name = info.get("InstanceType")
        out[name] = _parse_instance_spec(info)
    empty = InstanceSpec(gpu_count=0, gpu_spec=None, gpu_type=None, vcpu=0, memory_gib=0.0)
    for t in ec2_types:
        out.setdefault(t, empty)
    return out


async def get_gpu_counts(instance_types: list[str]) -> dict[str, int]:
    """批量返回 SageMaker 机型 -> 每实例 GPU 卡数 (0 = CPU)。"""
    specs = await get_instance_specs(instance_types)
    return {ml: s.gpu_count for ml, s in specs.items()}


async def get_gpu_infos(instance_types: list[str]) -> dict[str, InstanceSpec]:
    """向后兼容别名: 现返回完整 InstanceSpec (旧调用方只用 .count/.spec)。"""
    return await get_instance_specs(instance_types)


async def get_instance_specs(instance_types: list[str]) -> dict[str, InstanceSpec]:
    """批量返回 SageMaker 机型 -> InstanceSpec (GPU/vCPU/内存/型号)。

    去重 + 剥 ml. 前缀, 一次 describe_instance_types 查全部机型。返回键用原始 ml. 名。
    整批失败 (EC2 异常) -> 全机型 InstanceSpec(0…) (按 CPU/未知, 不阻塞页面)。

    缓存语义: TtlCache 无 peek, 故本函数每次都全量打一次 EC2 (不预读缓存省调用);
    缓存仅保证跨调用同机型结果稳定 (get_or_load 命中即返回不调 loader)。集群机型
    个位到几十, 每次全量查可接受 (保持简单)。
    """
    empty = InstanceSpec(gpu_count=0, gpu_spec=None, gpu_type=None, vcpu=0, memory_gib=0.0)
    result: dict[str, InstanceSpec] = {}
    miss: dict[str, str] = {}
    for it in dict.fromkeys(instance_types):
        if not it:
            continue
        miss[_strip_ml_prefix(it)] = it
    if not miss:
        return result
    try:
        specs = await _describe_instance_specs_batch(list(miss.keys()))
    except Exception as exc:  # noqa: BLE001
        logger.warning("ec2.describe_batch_fail", err=str(exc))
        specs = {ec2: empty for ec2 in miss}
    cache = _get_cache()
    for ec2, ml in miss.items():
        spec = specs.get(ec2, empty)

        async def _loader(v: InstanceSpec = spec) -> InstanceSpec:
            return v

        result[ml] = await cache.get_or_load(ec2, _loader)
    return result
