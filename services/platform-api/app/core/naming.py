"""资源命名 util — 显示名 → DNS-1123 label + 随机后缀 (训练/推理共用)。

需求: 用户只填显示名 (可重复, 任意字符), 平台自动派生唯一 DNS 任务名:
    dns_name = sanitize(display_name) + "-" + <随机后缀>
随机后缀保证唯一, 免"提交才发现重名"。
"""

from __future__ import annotations

import re
import secrets

_DNS_MAX = 63
_SUFFIX_LEN = 10  # 随机后缀长度 (a-z0-9), 36^10 碰撞概率可忽略
_SUFFIX_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

# HyperPodPyTorchJob 名字上限 40 (比 DNS label 的 63 严), operator 的
# vhyperpodpytorchjob.kb.io webhook 卡: 超了报 "job name '...' exceeded maximum
# length of 40 characters". 实测 40 过 / 41 拒; operator 升级可能改这个数.
TRAINING_NAME_MAX = 40

# 硬限是 63 (CRD spec.modelName), 取 40 与训练一致.
INFERENCE_NAME_MAX = 40

# Kueue 给 worker pod 打的 pod-group-name label 里嵌了任务名, 值不能超 63.
# 实测 33 过 / 34 拒 (replicas=1); replicas 上限 256 时 group-index 占 3 位, 故取 31.
# 别放宽: 超限时 kueue label 全打不上, pod 永久 Pending 而 Workload 仍报 Admitted.
LLMD_NAME_MAX = 31

# KubeRay webhook 硬限: RayJob 名 ≤ 47 (实测 2026-08-26, 报 "RayJob name should be
# no more than 47 characters"; 非 pod 名/label 约束, 是 KubeRay 显式校验)。
RAYJOB_NAME_MAX = 47


def _random_suffix(n: int = _SUFFIX_LEN) -> str:
    return "".join(secrets.choice(_SUFFIX_ALPHABET) for _ in range(n))


def sanitize_dns_label(text: str, *, fallback: str = "task") -> str:
    """显示名 → DNS-1123 label 合法前缀 (不含随机后缀)。

    规则: 小写; 非 [a-z0-9] → '-'; 压缩连续 '-'; 去首尾 '-'; 字母开头;
    全非法 (如纯中文) → fallback。不截断到最终长度 (留给 make_dns_name 配后缀)。
    """
    s = (text or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)  # 非法字符 (含中文/空格/大写残留) → '-'
    s = re.sub(r"-+", "-", s).strip("-")  # 压缩 + 去首尾
    if not s or not s[0].isalpha():
        # 空 (纯中文/数字开头) → 加 fallback 前缀保证字母开头
        s = f"{fallback}-{s}".strip("-") if s else fallback
    return s


def make_dns_name(
    display_name: str, *, fallback: str = "task", max_total: int = _DNS_MAX
) -> str:
    """显示名 → 唯一 DNS-1123 任务名 = sanitize(显示名)[截断] + '-' + 10随机。

    总长 ≤ max_total (默认 63 = DNS label 上限; 训练传 TRAINING_NAME_MAX)。
    """
    suffix = _random_suffix()
    prefix_max = max_total - 1 - _SUFFIX_LEN  # 63 → 52; 40 → 29
    prefix = sanitize_dns_label(display_name, fallback=fallback)[:prefix_max].rstrip("-")
    if not prefix:
        prefix = fallback[:prefix_max]
    return f"{prefix}-{suffix}"
