"""纯解析/校验函数 · 无 IO.

用于把 K8s 资源量字符串 ("8Gi", "500m", "1Ti") 解析成我们 DB / API 用的数字.
所有函数保证:
    - 无副作用
    - 失败返回默认值或 None (绝不 raise · 调用方决定如何处理)

额外 Pydantic field_validator 的语义 (mountPath / name 保留字 / memory min 8Gi)
留在 `api/schemas.py` 的 VolumeMount / DevInstanceCreate 里, 因为它们天然绑
pydantic model, 搬出来反而绕路.
"""

from __future__ import annotations


def parse_gib(raw: str, fallback: int = 0) -> int:
    """把 '10Gi' / '1Ti' 解析成整数 GiB. 解析失败返 fallback."""
    s = str(raw).strip()
    if s.endswith("Gi"):
        try:
            return int(s[:-2])
        except ValueError:
            return fallback
    if s.endswith("Ti"):
        try:
            return int(s[:-2]) * 1024
        except ValueError:
            return fallback
    return fallback


def parse_cpu_millicores(raw: str) -> int:
    """把 '500m' / '2' / '2.5' 解析成整数 millicores. 解析失败返 2000 (2 vCPU)."""
    s = str(raw).strip()
    if s.endswith("m"):
        try:
            return int(s[:-1])
        except ValueError:
            return 2000
    try:
        return int(float(s) * 1000)
    except ValueError:
        return 2000


def parse_memory_mib(raw: str) -> int:
    """把 '8Gi' / '1024Mi' 解析成 MiB. 解析失败返 8192 (8 GiB)."""
    s = str(raw).strip()
    if s.endswith("Gi"):
        try:
            return int(s[:-2]) * 1024
        except ValueError:
            return 8192
    if s.endswith("Mi"):
        try:
            return int(s[:-2])
        except ValueError:
            return 8192
    return 8192


def parse_pvc_capacity_gib(capacity: dict | None) -> int | None:
    """把 PVC status.capacity {'storage': '100Gi'} 解析成整数 GiB. 缺省返 None."""
    if not capacity:
        return None
    raw = capacity.get("storage")
    if not raw:
        return None
    s = str(raw).strip()
    if s.endswith("Gi"):
        try:
            return int(s[:-2])
        except ValueError:
            return None
    if s.endswith("Ti"):
        try:
            return int(s[:-2]) * 1024
        except ValueError:
            return None
    if s.endswith("Mi"):
        try:
            return max(1, int(s[:-2]) // 1024)
        except ValueError:
            return None
    return None
