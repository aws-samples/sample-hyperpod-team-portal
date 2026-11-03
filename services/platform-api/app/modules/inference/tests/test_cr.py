"""Inference CR 渲染 + schema 测试.

覆盖:
    - render_inference_endpoint_cr 字段一路传到 CR (FSx/S3/HF 三模型源)
    - Smart Routing 4 策略字段
    - L2 KV Cache 字段开/关
    - SGLang args + metrics + env 渲染
    - InferenceCreate schema 默认值 / 校验失败场景
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.inference.api.schemas import (
    InferenceCreate,
    L2KvCacheConfig,
    ModelSourceFsx,
)
from app.modules.inference.domain.cr import (
    IEC_API_VERSION,
    IEC_KIND,
    render_inference_endpoint_cr,
)


def _make_payload(**overrides) -> InferenceCreate:
    # name 禁传 (后端派生); display_name 自身须 DNS 合法, 原来的 "Qwen3 0.6B" 会被 pattern 拒
    base = {
        "display_name": "qwen3-06b",
        "model_source_type": "fsx",
        "fsx": ModelSourceFsx(filesystem_id="fs-x", model_location="qwen3-0-6b"),
        "model_name": "qwen3-0-6b",
        "instance_type": "ml.g6.2xlarge",
    }
    base.update(overrides)
    return InferenceCreate.model_validate(base)


class TestSchemaDefaults:
    def test_default_framework_sglang(self) -> None:
        p = _make_payload()
        assert p.framework == "sglang"

    def test_default_routing_roundrobin(self) -> None:
        p = _make_payload()
        assert p.routing_strategy == "roundrobin"

    def test_default_l2_disabled(self) -> None:
        p = _make_payload()
        assert p.l2_kv_cache.enabled is False
        assert p.l2_kv_cache.backend == "redis"

    def test_default_metrics_enabled(self) -> None:
        p = _make_payload()
        assert p.metrics_enabled is True

    def test_default_image_sglang_official(self) -> None:
        p = _make_payload()
        assert p.image == "lmsysorg/sglang:latest"

    def test_default_invocation_endpoint_openai(self) -> None:
        p = _make_payload()
        assert p.invocation_endpoint == "v1/chat/completions"


def _missing_source(source_type: str) -> None:
    """只缺模型源子对象, 其余全合法 → 报错必须落在模型源上, 不能落在 name/display_name。"""
    with pytest.raises(ValidationError) as ei:
        InferenceCreate.model_validate({
            "display_name": "src-check",
            "model_source_type": source_type,
            "instance_type": "ml.g6.2xlarge",
        })
    locs = {loc for err in ei.value.errors() for loc in err["loc"]}
    assert "name" not in locs and "display_name" not in locs, ei.value.errors()


class TestSchemaValidation:
    def test_fsx_source_requires_fsx_field(self) -> None:
        _missing_source("fsx")

    def test_s3_source_requires_s3_field(self) -> None:
        _missing_source("s3")

    def test_hf_source_requires_hf_field(self) -> None:
        _missing_source("huggingface")

    def test_cpu_limit_below_request_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_payload(
                cpu_request_millicores=4000,
                cpu_limit_millicores=2000,
            )

    def test_memory_limit_below_request_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_payload(
                memory_request_mib=16384,
                memory_limit_mib=8192,
            )

    def test_invalid_routing_strategy_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _make_payload(routing_strategy="invalid")


class TestDisplayNameValidation:
    """display_name 是任务名前缀, 判定权在后端."""

    def _msg(self, value: object) -> str:
        with pytest.raises(ValidationError) as ei:
            _make_payload(display_name=value)
        return "; ".join(e["msg"] for e in ei.value.errors())

    def test_max_length_29_accepted(self) -> None:
        p = _make_payload(display_name="a" * 29)
        assert p.display_name == "a" * 29

    def test_chinese_rejected_with_plain_message(self) -> None:
        assert "中文" in self._msg("推理服务")

    def test_fullwidth_rejected(self) -> None:
        # 全角字符用 chr() 构造: 留在源码里的字面量看着和半角一样, 谁都分不出
        assert "中文" in self._msg("qwen" + chr(0xFF13))

    def test_tab_reported_as_charset_not_length(self) -> None:
        """制表符是 ASCII 但不可打印, 报字符集问题而不是含中文以外的错。"""
        assert "可打印" in self._msg("qwen\t3")

    def test_over_length_reports_actual_length(self) -> None:
        assert "实际 30" in self._msg("a" * 30)

    def test_too_short_rejected(self) -> None:
        assert "3-29" in self._msg("ab")

    def test_uppercase_rejected_by_pattern(self) -> None:
        assert self._msg("Qwen3")  # pattern 兜底, 不要求特定文案

    def test_trailing_hyphen_rejected(self) -> None:
        assert self._msg("qwen3-")

    def test_client_supplied_name_rejected(self) -> None:
        with pytest.raises(ValidationError) as ei:
            _make_payload(name="my-own-name")
        assert "由后端" in "; ".join(e["msg"] for e in ei.value.errors())

    def test_name_absent_is_ok(self) -> None:
        assert _make_payload().name is None


class TestCRRendering:
    def _render(self, **kw):
        defaults = dict(
            name="qwen3-06b-sglang",
            namespace="hyperpod-ns-demo",
            inference_id="inf-001",
            workspace_id="ws-001",
            creator_id="alice",
            model_name="qwen3-0-6b",
            model_source_type="fsx",
            fsx={"filesystem_id": "fs-x", "model_location": "qwen3-0-6b"},
            instance_type="ml.g6.2xlarge",
        )
        defaults.update(kw)
        return render_inference_endpoint_cr(**defaults)

    def test_api_version_kind_official(self) -> None:
        cr = self._render()
        assert cr["apiVersion"] == IEC_API_VERSION == "inference.sagemaker.aws.amazon.com/v1"
        assert cr["kind"] == IEC_KIND == "InferenceEndpointConfig"

    def test_metadata_namespace_name(self) -> None:
        cr = self._render(name="x", namespace="ns-a")
        assert cr["metadata"]["name"] == "x"
        assert cr["metadata"]["namespace"] == "ns-a"

    def test_business_labels_attached(self) -> None:
        cr = self._render(
            inference_id="iid-1", workspace_id="wid-1", creator_id="cid-1"
        )
        labels = cr["metadata"]["labels"]
        assert labels["platform.hyperpod.io/inference-id"] == "iid-1"
        assert labels["platform.hyperpod.io/workspace-id"] == "wid-1"
        assert labels["platform.hyperpod.io/creator-id"] == "cid-1"
        assert labels["platform.hyperpod.io/framework"] == "sglang"

    def test_fsx_model_source(self) -> None:
        cr = self._render(
            model_source_type="fsx",
            fsx={
                "filesystem_id": "fs-abc",
                "model_location": "qwen3",
                "mount_name": "mn1",
                "dns_name": "dns1",
            },
        )
        msc = cr["spec"]["modelSourceConfig"]
        assert msc["modelSourceType"] == "fsx"
        assert msc["fsxStorage"]["fileSystemId"] == "fs-abc"
        assert msc["fsxStorage"]["mountName"] == "mn1"
        assert msc["fsxStorage"]["dnsName"] == "dns1"
        assert msc["modelLocation"] == "qwen3"

    def test_s3_model_source(self) -> None:
        cr = self._render(
            model_source_type="s3",
            fsx=None,
            s3={
                "bucket_name": "my-bucket",
                "region": "us-west-2",
                "model_location": "models/qwen3",
                "prefetch_enabled": True,
            },
        )
        msc = cr["spec"]["modelSourceConfig"]
        assert msc["modelSourceType"] == "s3"
        assert msc["s3Storage"]["bucketName"] == "my-bucket"
        assert msc["s3Storage"]["region"] == "us-west-2"
        assert msc["modelLocation"] == "models/qwen3"
        assert msc["prefetchEnabled"] is True

    def test_hf_model_source(self) -> None:
        cr = self._render(
            model_source_type="huggingface",
            fsx=None,
            hf={"model_id": "Qwen/Qwen3-0.6B", "prefetch_enabled": True},
        )
        msc = cr["spec"]["modelSourceConfig"]
        assert msc["modelSourceType"] == "huggingface"
        assert msc["huggingFaceModel"]["modelId"] == "Qwen/Qwen3-0.6B"

    def test_sglang_args_default(self) -> None:
        # context_length 已并入 args 框, render 不再收该参数; 默认 args 仍含 --context-length 8192
        cr = self._render(container_port=8000)
        args = cr["spec"]["worker"]["args"]
        assert "--model-path" in args
        assert "/opt/ml/model" in args
        assert "--port" in args
        assert "8000" in args
        assert "--enable-metrics" in args
        assert "--context-length" in args
        assert "8192" in args

    def test_sglang_extra_args_appended(self) -> None:
        cr = self._render(sglang_extra_args=["--mem-fraction-static", "0.85"])
        args = cr["spec"]["worker"]["args"]
        assert "--mem-fraction-static" in args
        assert "0.85" in args

    def test_metrics_block_when_enabled(self) -> None:
        cr = self._render(metrics_enabled=True, container_port=8000)
        m = cr["spec"]["metrics"]
        assert m["enabled"] is True
        assert m["modelMetrics"]["port"] == 8000
        assert m["modelMetrics"]["path"] == "/metrics"

    def test_metrics_block_absent_when_disabled(self) -> None:
        cr = self._render(metrics_enabled=False)
        assert "metrics" not in cr["spec"]

    def test_routing_roundrobin_omitted(self) -> None:
        """默认 roundrobin 不写 spec.routingStrategy (省 yaml)."""
        cr = self._render(routing_strategy="roundrobin")
        assert "routingStrategy" not in cr["spec"]

    def test_routing_kvaware_attached(self) -> None:
        # 路由嵌在 spec.intelligentRoutingSpec 下 (顶层 spec.routingStrategy 会被 K8s reject)
        cr = self._render(routing_strategy="kvaware")
        assert cr["spec"]["intelligentRoutingSpec"]["enabled"] is True
        assert cr["spec"]["intelligentRoutingSpec"]["routingStrategy"] == "kvaware"

    def test_routing_prefixaware_attached(self) -> None:
        cr = self._render(routing_strategy="prefixaware")
        assert cr["spec"]["intelligentRoutingSpec"]["enabled"] is True
        assert cr["spec"]["intelligentRoutingSpec"]["routingStrategy"] == "prefixaware"

    def test_routing_session_attached(self) -> None:
        cr = self._render(routing_strategy="session")
        assert cr["spec"]["intelligentRoutingSpec"]["enabled"] is True
        assert cr["spec"]["intelligentRoutingSpec"]["routingStrategy"] == "session"

    def test_l2_disabled_omits_kv_cache_block(self) -> None:
        cr = self._render(l2_kv_cache={"enabled": False})
        assert "kvCache" not in cr["spec"]

    def test_l2_enabled_attaches_kv_cache_block(self) -> None:
        cr = self._render(
            l2_kv_cache={
                "enabled": True,
                "backend": "redis",
                "redis_endpoint": "redis-master.kvcache:6379",
            }
        )
        kv = cr["spec"]["kvCache"]["l2"]
        assert kv["enabled"] is True
        assert kv["backend"] == "redis"
        assert kv["endpoint"] == "redis-master.kvcache:6379"
        assert kv["hitRatioMetricEnabled"] is True

    def test_resources_request_limit(self) -> None:
        cr = self._render(
            gpu_per_replica=2,
            cpu_request_millicores=4000,
            cpu_limit_millicores=8000,
            memory_request_mib=16384,
            memory_limit_mib=32768,
        )
        r = cr["spec"]["worker"]["resources"]
        assert r["requests"]["nvidia.com/gpu"] == "2"
        assert r["requests"]["cpu"] == "4000m"
        assert r["requests"]["memory"] == "16384Mi"
        assert r["limits"]["nvidia.com/gpu"] == "2"
        assert r["limits"]["cpu"] == "8000m"
        assert r["limits"]["memory"] == "32768Mi"

    def test_default_env_vars_attached(self) -> None:
        cr = self._render()
        env_list = cr["spec"]["worker"]["environmentVariables"]
        env_map = {e["name"]: e["value"] for e in env_list}
        assert env_map["HF_HOME"] == "/opt/ml/model"
        assert env_map["HF_HUB_OFFLINE"] == "1"
        assert env_map["SGLANG_DISABLE_USAGE_STATS"] == "1"

    def test_user_env_overrides_default(self) -> None:
        cr = self._render(env={"HF_HUB_OFFLINE": "0", "MY_VAR": "abc"})
        env_list = cr["spec"]["worker"]["environmentVariables"]
        env_map = {e["name"]: e["value"] for e in env_list}
        assert env_map["HF_HUB_OFFLINE"] == "0"  # 用户覆盖
        assert env_map["MY_VAR"] == "abc"
        assert env_map["HF_HOME"] == "/opt/ml/model"  # 默认仍在

    def test_invocation_endpoint_default_openai(self) -> None:
        cr = self._render()
        assert cr["spec"]["invocationEndpoint"] == "v1/chat/completions"

    def test_replicas_passed(self) -> None:
        cr = self._render(replicas=3)
        assert cr["spec"]["replicas"] == 3


class TestL2KvCacheConfig:
    def test_default_config(self) -> None:
        cfg = L2KvCacheConfig()
        assert cfg.enabled is False
        assert cfg.backend == "redis"
        assert "redis-master" in cfg.redis_endpoint
