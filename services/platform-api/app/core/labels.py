"""用户自定义 label 校验 (训练/推理共用)。

裸 key, 后端强校验: 拒保留前缀 (防篡改平台/调度 label) + RFC 1123 合法性 + 数量上限。
"""

from __future__ import annotations

import re

from fastapi import HTTPException

from app.core.i18n import t

_MAX_LABELS = 10
_RESERVED_PREFIXES = (
    "platform.hyperpod.io/",
    "kueue.x-k8s.io/",
    "sagemaker.",
    "kubernetes.io/",
    "k8s.io/",
    "app.kubernetes.io/",
)
_NAME_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9._-]{0,61}[a-zA-Z0-9])?$")
_PREFIX_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")


def _reject(msg: str) -> None:
    raise HTTPException(422, msg)


def _check_key(key: str) -> None:
    low = key.lower()
    for p in _RESERVED_PREFIXES:
        if low.startswith(p):
            _reject(t("core.label_reserved_prefix", key=key, prefix=p))
    prefix, _, name = key.rpartition("/")
    if prefix and not _PREFIX_RE.match(prefix):
        _reject(t("core.label_prefix_invalid", prefix=prefix))
    if not _NAME_RE.match(name):
        _reject(t("core.label_name_invalid", name=name))


def _check_value(key: str, value: str) -> None:
    if value and not _NAME_RE.match(value):
        _reject(t("core.label_value_invalid", key=key, value=value))


def sanitize_label_value(value: str, *, fallback: str = "unknown") -> str:
    """把任意字符串合法化成 K8s label value (RFC 1123)。

    用于系统注入的 label (如 creator-id = IdC username, 可能是邮箱格式含 @/大小写),
    K8s label value 只允许 [A-Za-z0-9._-], 首尾必须字母数字, ≤63 字符。
    非法字符 → '_', 裁掉首尾非字母数字, 超长截断。空/全非法 → fallback。

    例: 'jane.doe@example.com' → 'jane.doe_example.com'
    """
    if not value:
        return fallback
    # 非法字符替换为 _
    s = re.sub(r"[^A-Za-z0-9._-]", "_", value.strip())
    # 截断到 63
    s = s[:63]
    # 裁掉首尾非字母数字 (label value 必须字母数字起止)
    s = re.sub(r"^[^A-Za-z0-9]+", "", s)
    s = re.sub(r"[^A-Za-z0-9]+$", "", s)
    return s or fallback


def validate_user_labels(labels: dict[str, str] | None) -> dict[str, str]:
    """校验用户自定义 label, 返回清洗后的 dict。任一不过抛 422。"""
    if not labels:
        return {}
    if len(labels) > _MAX_LABELS:
        _reject(t("core.label_too_many", max=_MAX_LABELS, actual=len(labels)))
    out: dict[str, str] = {}
    for key, value in labels.items():
        key = (key or "").strip()
        value = (value or "").strip()
        if not key:
            _reject(t("core.label_key_empty"))
        _check_key(key)
        _check_value(key, value)
        out[key] = value
    return out
