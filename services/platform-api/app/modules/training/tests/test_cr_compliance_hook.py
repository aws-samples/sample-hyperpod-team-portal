"""Training 模块本地 CR 合规钩子测试.

校验 HyperPodPyTorchJob 渲染输出符合官方 CRD 关键约束 (apiVersion/kind,
runPolicy, Kueue label 位置, 资源/env 渲染等), 防止 CR schema 漂移.

跑法::
    pytest app/modules/training/tests/test_cr_compliance_hook.py -v
"""

from __future__ import annotations

import pytest

from app.modules.training.domain.cr import (
    HPJ_API_VERSION,
    HPJ_KIND,
    render_hp_pytorch_job_cr,
)

pytestmark = pytest.mark.cr_compliance


@pytest.fixture
def rendered_cr() -> dict:
    return render_hp_pytorch_job_cr(
        name="hpj-demo-abc123",
        namespace="default",
        image="pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime",
        command="python /workspace/train.py",
        node_count=2,
        gpu_per_node=8,
        cpu_per_node_millicores=8000,
        memory_per_node_mib=65536,
        training_job_id="11111111-2222-3333-4444-555555555555",
        workspace_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        creator_id="00000000-1111-2222-3333-444444444444",
    )


class TestCRSchemaCompliance:
    """渲染器输出必须是官方样板 key 路径的子集 (含精准白名单)."""

    def test_api_version_and_kind_are_official(self, rendered_cr: dict) -> None:
        assert rendered_cr["apiVersion"] == HPJ_API_VERSION == "sagemaker.amazonaws.com/v1"
        assert rendered_cr["kind"] == HPJ_KIND == "HyperPodPyTorchJob"

    def test_nproc_per_node_is_string(self, rendered_cr: dict) -> None:
        """CRD schema 强制 nprocPerNode: string · 写 int 会被 openAPIV3 拒."""
        nproc = rendered_cr["spec"]["nprocPerNode"]
        assert isinstance(nproc, str), f"nprocPerNode 必须是 string, 实际: {type(nproc)}"
        assert nproc == "8"

    def test_replica_specs_name_required(self, rendered_cr: dict) -> None:
        specs = rendered_cr["spec"]["replicaSpecs"]
        assert len(specs) == 1
        assert specs[0]["name"] == "pods"
        assert specs[0]["replicas"] == 2

    def test_run_policy_strictly_official(self, rendered_cr: dict) -> None:
        """runPolicy 默认值对齐产品决策 + 官方 CRD default."""
        rp = rendered_cr["spec"]["runPolicy"]
        assert rp["cleanPodPolicy"] == "All"  # 结束清全部 Pod (前后端默认对齐)
        assert rp["ttlSecondsAfterFinished"] == -1
        assert rp["jobMaxRetryCount"] == 0
        restart = rp["restartPolicy"]
        assert restart["numRestartBeforeFullJobRestart"] == 3
        assert restart["evalPeriodSeconds"] == 3600  # CRD required
        assert restart["maxFullJobRestarts"] == 1

    def test_agent_port_8080_present(self, rendered_cr: dict) -> None:
        """HyperPodElasticAgent 监听 port 必须是 8080 (operator 轮询口)."""
        container = rendered_cr["spec"]["replicaSpecs"][0]["template"]["spec"][
            "containers"
        ][0]
        ports = container["ports"]
        assert any(p["containerPort"] == 8080 for p in ports)

    def test_kueue_queue_label_on_cr_metadata(self, rendered_cr: dict) -> None:
        """Kueue admission 必备 label 必须在 CR 顶层 metadata (operator 自传到 pod)."""
        labels = rendered_cr["metadata"]["labels"]
        assert labels["kueue.x-k8s.io/queue-name"] == "default-localqueue"

    def test_pod_template_has_no_kueue_label(self, rendered_cr: dict) -> None:
        """Pod template 不应重复放 kueue label · 避免两处漂移."""
        pod_spec = rendered_cr["spec"]["replicaSpecs"][0]["template"]
        # pod template 可以没有 metadata, 也可以有 metadata 但不含 kueue label
        pod_labels = (pod_spec.get("metadata") or {}).get("labels") or {}
        assert "kueue.x-k8s.io/queue-name" not in pod_labels


class TestRunPolicyOverrides:
    """runPolicy 可配字段的 override 路径."""

    def test_clean_pod_policy_override(self) -> None:
        cr = render_hp_pytorch_job_cr(
            name="x", namespace="default", image="pytorch",
            command="python x.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
            clean_pod_policy="OnlyComplete",
        )
        assert cr["spec"]["runPolicy"]["cleanPodPolicy"] == "OnlyComplete"

    def test_active_deadline_seconds_optional(self) -> None:
        """不传时 activeDeadlineSeconds 字段不应出现 (optional)."""
        cr = render_hp_pytorch_job_cr(
            name="x", namespace="default", image="pytorch",
            command="python x.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
        )
        assert "activeDeadlineSeconds" not in cr["spec"]["runPolicy"]

    def test_active_deadline_seconds_included_when_set(self) -> None:
        cr = render_hp_pytorch_job_cr(
            name="x", namespace="default", image="pytorch",
            command="python x.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
            active_deadline_seconds=7200,
        )
        assert cr["spec"]["runPolicy"]["activeDeadlineSeconds"] == 7200

    def test_job_max_retry_count_override(self) -> None:
        cr = render_hp_pytorch_job_cr(
            name="x", namespace="default", image="pytorch",
            command="python x.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
            job_max_retry_count=10,
        )
        assert cr["spec"]["runPolicy"]["jobMaxRetryCount"] == 10


class TestResourceRendering:
    def test_gpu_zero_omits_nvidia_gpu_limit(self) -> None:
        """CPU-only 训练 (gpu=0) 不应写 nvidia.com/gpu: 0 (会被调度器拒)."""
        cr = render_hp_pytorch_job_cr(
            name="x", namespace="default", image="pytorch",
            command="python x.py", node_count=1, gpu_per_node=0,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
        )
        container = cr["spec"]["replicaSpecs"][0]["template"]["spec"]["containers"][0]
        assert "nvidia.com/gpu" not in container["resources"]["requests"]
        assert "nvidia.com/gpu" not in container["resources"]["limits"]

    def test_nccl_defaults_auto_injected(self) -> None:
        cr = render_hp_pytorch_job_cr(
            name="x", namespace="default", image="pytorch",
            command="python x.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
        )
        # 只看有 value 的项 · valueFrom 类 (Downward API 的 fieldRef / secretKeyRef)
        # 没有 value 键, 不过滤会 KeyError。
        env_dict = {
            e["name"]: e["value"]
            for e in cr["spec"]["replicaSpecs"][0]["template"]["spec"]["containers"][0][
                "env"
            ]
            if "value" in e
        }
        assert env_dict["NCCL_DEBUG"] == "INFO"
        assert env_dict["NCCL_ASYNC_ERROR_HANDLING"] == "1"
        assert env_dict["PYTHONUNBUFFERED"] == "1"

    def test_user_env_overrides_default(self) -> None:
        """用户显式传的 NCCL_DEBUG 必须压过默认值."""
        cr = render_hp_pytorch_job_cr(
            name="x", namespace="default", image="pytorch",
            command="python x.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
            env={"NCCL_DEBUG": "WARN"},
        )
        env_list = cr["spec"]["replicaSpecs"][0]["template"]["spec"]["containers"][0][
            "env"
        ]
        debug_vals = [e["value"] for e in env_list if e["name"] == "NCCL_DEBUG"]
        assert debug_vals == ["WARN"]

    def test_downward_api_env_injected(self) -> None:
        """NODE_NAME / POD_NAME 走 Downward API 注入, fieldPath 必须精确.

        写错的 fieldPath admission webhook 不拦, 要等 kubelet 起容器才报
        CreateContainerConfigError, 所以在这里钉死字符串.
        """
        cr = render_hp_pytorch_job_cr(
            name="x", namespace="default", image="pytorch",
            command="python x.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
        )
        env_list = cr["spec"]["replicaSpecs"][0]["template"]["spec"]["containers"][0][
            "env"
        ]
        by_name = {e["name"]: e for e in env_list}
        assert by_name["NODE_NAME"]["valueFrom"]["fieldRef"]["fieldPath"] == "spec.nodeName"
        assert by_name["POD_NAME"]["valueFrom"]["fieldRef"]["fieldPath"] == "metadata.name"
        # valueFrom 与 value 互斥, 同时写会被 API server 拒
        assert "value" not in by_name["NODE_NAME"]
        assert "value" not in by_name["POD_NAME"]

    def test_user_env_overrides_downward_one_by_one(self) -> None:
        """用户只覆盖 POD_NAME 时 NODE_NAME 仍由平台注入 (逐项判断, 不整体跳过)."""
        cr = render_hp_pytorch_job_cr(
            name="x", namespace="default", image="pytorch",
            command="python x.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
            env={"POD_NAME": "my-own-value"},
        )
        env_list = cr["spec"]["replicaSpecs"][0]["template"]["spec"]["containers"][0][
            "env"
        ]
        # 用户值胜出且只出现一次 (重复 name 会让后者静默覆盖前者, 难查)
        assert [e for e in env_list if e["name"] == "POD_NAME"] == [
            {"name": "POD_NAME", "value": "my-own-value"}
        ]
        node_entries = [e for e in env_list if e["name"] == "NODE_NAME"]
        assert len(node_entries) == 1
        assert node_entries[0]["valueFrom"]["fieldRef"]["fieldPath"] == "spec.nodeName"


class TestBusinessLabels:
    def test_business_labels_only_when_provided(self) -> None:
        """3 个业务追溯 label 可选 · 不传时不出现."""
        cr = render_hp_pytorch_job_cr(
            name="x", namespace="default", image="pytorch",
            command="python x.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
        )
        labels = cr["metadata"]["labels"]
        assert "platform.hyperpod.io/training-job-id" not in labels
        assert labels["kueue.x-k8s.io/queue-name"] == "default-localqueue"
