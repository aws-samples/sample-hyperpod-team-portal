"""PromQL 模板变量替换 + 折叠分组 (纯字符串操作, 无 IO)."""

from __future__ import annotations

from app.core.i18n import has, t
from app.modules.monitoring.api.schemas import QueryTemplate

# category → 分组 slug (展示名在文案表 monitoring.group.<slug>)。event 与 status 同组。
_CATEGORY_GROUP = {
    "efa": "efa",
    "cpu": "cpu",
    "memory": "memory",
    "disk": "disk",
    "network": "network",
    "process": "process",
    "training": "training",
    "status": "status",
    "event": "status",
    "sglang": "sglang",
    "inference": "inference",
    "fsx": "fsx",
    "mlflow": "mlflow",
}

# gpu 按 key 关键词细分 (参考 Grafana 面板分区), 顺序敏感: 专项组优先于"性能"兜底
_GPU_GROUP_RULES = [
    (("nvlink",), "gpu_nvlink"),
    (("ecc", "xid", "remap", "retired", "violation", "reliability", "replay"), "gpu_health"),
    (("temp", "power", "clock", "energy", "fan"), "gpu_clock_power"),
    (("fb", "bar1", "dram", "_mem"), "gpu_memory"),
]


# CPU/内存/磁盘/网络 在 pod 维度各有 7-11 个指标 (独立成组); job/inference/dev
# 维度各只 1-2 个, 合成一个 "CPU / 内存 / 磁盘 / 网络" 组避免碎组. 用 key 前缀区分:
# pod 维度 key 形如 pod_cpu_*, 其余维度 (job_*/inf_*/裸 cpu_*) 合并.
_NODE_RES_CATEGORIES = {"cpu", "memory", "disk", "network"}

# sglang 31 个指标按 key 关键词细分 (参考 SGLang dashboard), 顺序敏感.
_SGLANG_GROUP_RULES = [
    (("ttft", "itl", "e2e", "queue_p", "_forward", "_process"), "sglang_latency"),
    (("kv_", "cache", "token_usage", "utilization", "capacity"), "sglang_kv_cache"),
    (("running_reqs", "queue_reqs", "http_active"), "sglang_queue"),
]

# dynamo 引擎指标按 key 关键词细分 (照 sglang), 顺序敏感: 延迟组含 kv_transfer,
# 故先于 KV Cache 组匹配, 避免 dyn_kv_transfer_p95 被"kv"关键词抢到 KV Cache 组.
_DYNAMO_GROUP_RULES = [
    (("ttft", "itl", "duration", "load_time", "first_response", "permit_wait",
      "kv_transfer", "tokenize", "router_sched", "router_overhead"), "dynamo_latency"),
    (("gpu_cache", "kv_hit", "total_blocks", "shared_cache", "model_context",
      "model_total_kv"), "dynamo_kv_cache"),
    (("inflight", "queue_depth", "queue_capacity", "enqueue_rejected",
      "pool_active", "pool_capacity", "disconnected"), "dynamo_queue"),
]


def _group_of(tpl: QueryTemplate) -> str:
    """返回分组 slug (稳定标识, 前端按它排序)。"""
    if tpl.category in _NODE_RES_CATEGORIES and not tpl.key.startswith("pod_"):
        return "node_resources"
    if tpl.category == "sglang":
        k = tpl.key
        for words, grp in _SGLANG_GROUP_RULES:
            if any(w in k for w in words):
                return grp
        return "sglang_throughput"  # gen_throughput / *_rate / *_tokens_avg 等兜底
    if tpl.category == "dynamo":
        k = tpl.key
        for words, grp in _DYNAMO_GROUP_RULES:
            if any(w in k for w in words):
                return grp
        return "dynamo_throughput"  # request_rate / frontend_qps / cancellation / *_seq / uptime 兜底
    if tpl.category != "gpu":
        return _CATEGORY_GROUP.get(tpl.category, tpl.category)
    # GPU 子组细分只对训练单卡指标 (key 前缀 gpu_card_, 47 个) 有意义.
    # job 聚合 / pod / inference (inf_gpu_*) / dev (gpu_*) 的 GPU 只 4-19 个,
    # 细分会产生 1-2 个图的碎组, 统一归一个 "GPU" 组.
    k = tpl.key
    if not k.startswith("gpu_card_"):
        return "gpu"
    for words, grp in _GPU_GROUP_RULES:
        if any(w in k for w in words):
            return grp
    return "gpu_perf"


# 组内展示顺序。前端只排 group 不排组内; 未列出的排组尾
_KEY_ORDER = {
    # ── 延迟: TTFT → E2E → Queue → 分阶段
    "inf_sgl_ttft_p50": 10, "inf_sgl_ttft_p95": 11, "inf_sgl_ttft_p99": 12,
    "inf_sgl_e2e_p50": 20, "inf_sgl_e2e_p95": 21, "inf_sgl_e2e_p99": 22,
    "inf_sgl_queue_p50": 30, "inf_sgl_queue_p95": 31,
    "inf_sgl_prefill_forward_p95": 40,
    "inf_sgl_request_process_p95": 41,
    # ── 吞吐: 速率 → 平均量 → HTTP
    "inf_sgl_request_rate": 50,
    "inf_sgl_prompt_tokens_rate": 51,
    "inf_sgl_generation_tokens_rate": 52,
    "inf_sgl_gen_throughput": 53,
    "inf_sgl_prompt_tokens_avg": 54,
    "inf_sgl_generation_tokens_avg": 55,
    "inf_sgl_http_requests_rate": 56,
    "inf_sgl_http_responses_rate": 57,
    # ── KV Cache: 比率 → 绝对量 (已用 → 可回收 → 空闲 → 总量)
    "inf_sgl_cache_hit_rate": 60,
    "inf_sgl_token_usage": 61,
    "inf_sgl_utilization": 62,
    "inf_sgl_kv_used_tokens": 63,
    "inf_sgl_kv_evictable_tokens": 64,
    "inf_sgl_kv_available_tokens": 65,
    "inf_sgl_kv_capacity": 66,
    "inf_sgl_uncached_prompt_tokens_avg": 67,
    # ── 队列与并发
    "inf_sgl_running_reqs": 70,
    "inf_sgl_queue_reqs": 71,
    "inf_sgl_http_active": 72,
}


def sort_templates(tpls: list[QueryTemplate]) -> list[QueryTemplate]:
    """按 _KEY_ORDER 排序; 未列出的保持原相对顺序 (sorted 稳定)。"""
    return sorted(tpls, key=lambda tpl: _KEY_ORDER.get(tpl.key, 999))


def localize_template(tpl: QueryTemplate) -> QueryTemplate:
    """按当前请求语言填 title / description / group 展示名, group_key 填稳定 slug (幂等)。

    slug 取模板显式 group_key (如 Ray 的 ray_*), 否则按 category/key 规则推导 (_group_of)。

    unit 一般是语言无关的符号, 仅当文案表有 monitoring.tpl.<key>.unit (原为中文单位) 时覆盖。
    """
    slug = tpl.group_key or _group_of(tpl)
    desc_key = f"monitoring.tpl.{tpl.key}.description"
    unit_key = f"monitoring.tpl.{tpl.key}.unit"
    return tpl.model_copy(
        update={
            "title": t(f"monitoring.tpl.{tpl.key}.title"),
            "description": t(desc_key) if has(desc_key) else None,
            "unit": t(unit_key) if has(unit_key) else tpl.unit,
            "group_key": slug,
            "group": t(f"monitoring.group.{slug}"),
        }
    )


def subst_template(tpl: QueryTemplate, **vars: str) -> QueryTemplate:
    """替换 promql 里的 $vars + 本地化展示文案, 返回新 QueryTemplate (不改原对象).

    占位符形如 ``$namespace`` / ``$pod_regex``; 直接字符串替换, 不解析 Prometheus 表达式.
    """
    q = tpl.promql
    for k, v in vars.items():
        q = q.replace(f"${k}", v)
    return localize_template(tpl.model_copy(update={"promql": q}))
