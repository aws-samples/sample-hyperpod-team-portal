"""Orchestration 层测试 · 验证 CR 渲染入口正确接到 domain, runPolicy 字段齐活.

重业务流 (DB + K8s API 双 side-effect) 留给 integration 层跑, 这里只用纯函数
断言确保 create 流程把 payload 正确拼入 CR.
"""

from __future__ import annotations

from uuid import uuid4

from app.modules.training.api.schemas import TrainingJobCreate
from app.modules.training.domain.cr import render_hp_pytorch_job_cr


def _make_payload(**overrides) -> TrainingJobCreate:
    # name 禁传 (后端派生); display_name 自身须 DNS 合法, 原来的 "Test Job" 会被 pattern 拒
    base = {
        "display_name": "test-job",
        "image": "pytorch:latest",
        "command": "python train.py",
        "node_count": 1,
        "gpu_per_node": 1,
        "cpu_per_node_millicores": 1000,
        "memory_per_node_mib": 1024,
        "env": {},
    }
    base.update(overrides)
    return TrainingJobCreate.model_validate(base)


def _job_name(payload: TrainingJobCreate) -> str:
    """K8s 任务名 · 与 create_training_job_flow 同源派生 (payload.name 恒为 None)。"""
    from app.core.naming import TRAINING_NAME_MAX, make_dns_name

    return make_dns_name(
        payload.display_name, fallback="train", max_total=TRAINING_NAME_MAX
    )


class TestCreatePayloadToCR:
    """payload 字段一路传到 CR 渲染 · 没有字段被 orchestration 吞掉."""

    def test_run_policy_fields_flow_to_cr(self) -> None:
        payload = _make_payload(
            clean_pod_policy="OnlyComplete",
            ttl_seconds_after_finished=300,
            job_max_retry_count=5,
            active_deadline_seconds=1800,
        )
        cr = render_hp_pytorch_job_cr(
            name=_job_name(payload),
            namespace="default",
            image=payload.image,
            command=payload.command,
            node_count=payload.node_count,
            gpu_per_node=payload.gpu_per_node,
            cpu_per_node_millicores=payload.cpu_per_node_millicores,
            memory_per_node_mib=payload.memory_per_node_mib,
            clean_pod_policy=payload.clean_pod_policy,
            ttl_seconds_after_finished=payload.ttl_seconds_after_finished,
            job_max_retry_count=payload.job_max_retry_count,
            active_deadline_seconds=payload.active_deadline_seconds,
        )
        rp = cr["spec"]["runPolicy"]
        assert rp["cleanPodPolicy"] == "OnlyComplete"
        assert rp["ttlSecondsAfterFinished"] == 300
        assert rp["jobMaxRetryCount"] == 5
        assert rp["activeDeadlineSeconds"] == 1800

    def test_multi_node_rendering(self) -> None:
        payload = _make_payload(node_count=4, gpu_per_node=8)
        cr = render_hp_pytorch_job_cr(
            name=_job_name(payload),
            namespace="default",
            image=payload.image,
            command=payload.command,
            node_count=payload.node_count,
            gpu_per_node=payload.gpu_per_node,
            cpu_per_node_millicores=payload.cpu_per_node_millicores,
            memory_per_node_mib=payload.memory_per_node_mib,
        )
        assert cr["spec"]["replicaSpecs"][0]["replicas"] == 4
        assert cr["spec"]["nprocPerNode"] == "8"

    def test_business_ids_land_on_cr_labels(self) -> None:
        tid = str(uuid4())
        wid = str(uuid4())
        cid = str(uuid4())
        cr = render_hp_pytorch_job_cr(
            name="x", namespace="default", image="pytorch",
            command="python x.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
            training_job_id=tid, workspace_id=wid, creator_id=cid,
        )
        labels = cr["metadata"]["labels"]
        assert labels["platform.hyperpod.io/training-job-id"] == tid
        assert labels["platform.hyperpod.io/workspace-id"] == wid
        assert labels["platform.hyperpod.io/creator-id"] == cid


class TestFsxMounts:
    """FSx 全平等挂载 (extra_fsx_mounts, 后端反查授权真值), 无 /fsx 主盘特殊语义。
    securityContext runAsGroup = run_as_group (ws primary_gid 兜底), 所有 FSx gid 进
    supplementalGroups + S3 1001。代码/checkpoint 路径用户自己写。
    """

    def test_fsx_mounts_rendered_by_authorized_path(self) -> None:
        # 每个 FSx 按授权 mount_path 挂; read_only 取授权值
        cr = render_hp_pytorch_job_cr(
            name="x", namespace="default", image="pytorch",
            command="python /data/train.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
            extra_fsx_mounts=[
                {"pvc_name": "pvc-a", "mount_path": "/data", "read_only": False},
                {"pvc_name": "pvc-b", "mount_path": "/ref", "read_only": True},
            ],
        )
        pod_spec = cr["spec"]["replicaSpecs"][0]["template"]["spec"]
        mounts = pod_spec["containers"][0]["volumeMounts"]
        by_path = {m["mountPath"]: m for m in mounts}
        assert by_path["/data"].get("readOnly") is False
        assert by_path["/ref"]["readOnly"] is True
        # 无 /fsx 主盘
        assert "/fsx" not in by_path
        vol_pvcs = {
            v["persistentVolumeClaim"]["claimName"]
            for v in pod_spec["volumes"] if "persistentVolumeClaim" in v
        }
        assert {"pvc-a", "pvc-b"} <= vol_pvcs

    def test_no_fsx_mount_when_empty(self) -> None:
        # 没选 FSx → 只有 dshm, 无 /fsx
        cr = render_hp_pytorch_job_cr(
            name="x", namespace="default", image="pytorch",
            command="python train.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
        )
        pod_spec = cr["spec"]["replicaSpecs"][0]["template"]["spec"]
        paths = [m["mountPath"] for m in pod_spec["containers"][0]["volumeMounts"]]
        assert paths == ["/dev/shm"]

    def test_no_init_container(self) -> None:
        cr = render_hp_pytorch_job_cr(
            name="x", namespace="default", image="pytorch",
            command="python train.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
            extra_fsx_mounts=[{"pvc_name": "pvc-a", "mount_path": "/data", "read_only": False}],
        )
        assert "initContainers" not in cr["spec"]["replicaSpecs"][0]["template"]["spec"]

    def test_env_secrets_render_secret_key_ref(self) -> None:
        # env_secrets → 主容器 env valueFrom.secretKeyRef (值不进明文),
        # 无 initContainer (github clone 已废弃)。
        cr = render_hp_pytorch_job_cr(
            name="x", namespace="default", image="pytorch",
            command="python train.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
            env_secrets=[
                {"name": "GITHUB_TOKEN", "secret_ref": "alice-creds", "secret_key": "GITHUB_TOKEN"},
            ],
        )
        spec = cr["spec"]["replicaSpecs"][0]["template"]["spec"]
        assert "initContainers" not in spec  # 不再 clone
        envs = {e["name"]: e for e in spec["containers"][0]["env"]}
        tok = envs["GITHUB_TOKEN"]
        assert "value" not in tok  # 不写明文
        assert tok["valueFrom"]["secretKeyRef"] == {"name": "alice-creds", "key": "GITHUB_TOKEN"}

    def test_command_passthrough_when_auto_wrap_off(self) -> None:
        # 默认 auto_wrap=False → command 原样下发 (用户自管路径, 平台不套壳)
        cr = render_hp_pytorch_job_cr(
            name="j", namespace="default", image="pytorch",
            command="bash /data/hypd_run_elastic.sh",
            node_count=1, gpu_per_node=2,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
        )
        full = cr["spec"]["replicaSpecs"][0]["template"]["spec"]["containers"][0]["command"]
        assert full[:2] == ["/bin/bash", "-lc"]
        assert full[2] == "bash /data/hypd_run_elastic.sh"
        assert "hyperpodrun" not in full[2]

    def test_command_list_passthrough_as_exec_array(self) -> None:
        cr = render_hp_pytorch_job_cr(
            name="j", namespace="default", image="pytorch",
            command=["bash", "/data/code/start.sh"],
            node_count=1, gpu_per_node=2,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
        )
        full = cr["spec"]["replicaSpecs"][0]["template"]["spec"]["containers"][0]["command"]
        assert full == ["bash", "/data/code/start.sh"]

    def test_security_context_with_run_as_group(self) -> None:
        # run_as_group → runAsUser=0 + runAsGroup/fsGroup=primary_gid;
        # supplementalGroups = 所有 FSx gid + S3 1001 (去重排序)
        cr = render_hp_pytorch_job_cr(
            name="j", namespace="default", image="pytorch",
            command="python /data/train.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
            run_as_group=5001,
            fsx_supplemental_gids=[5001, 5002],
        )
        sc = cr["spec"]["replicaSpecs"][0]["template"]["spec"]["securityContext"]
        assert sc["runAsUser"] == 0
        assert sc["runAsGroup"] == 5001
        assert sc["fsGroup"] == 5001
        assert sc["fsGroupChangePolicy"] == "OnRootMismatch"
        # 5001+5002 (FSx) + 1001 (S3), 去重排序
        assert sc["supplementalGroups"] == [1001, 5001, 5002]

    def test_no_security_context_without_run_as_group(self) -> None:
        # 没 run_as_group (无 primary_gid 无 FSx) → 不设 securityContext
        cr = render_hp_pytorch_job_cr(
            name="j", namespace="default", image="pytorch",
            command="python train.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
        )
        assert "securityContext" not in cr["spec"]["replicaSpecs"][0]["template"]["spec"]

    def test_instance_type_renders_nodeselector(self) -> None:
        # instance_type → pod nodeSelector 锁机型 (Kueue 据此选 flavor)
        cr = render_hp_pytorch_job_cr(
            name="j", namespace="default", image="pytorch",
            command="python train.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
            instance_type="ml.m5.4xlarge",
        )
        ns = cr["spec"]["replicaSpecs"][0]["template"]["spec"]["nodeSelector"]
        assert ns == {"node.kubernetes.io/instance-type": "ml.m5.4xlarge"}

    def test_no_nodeselector_without_instance_type(self) -> None:
        # 没传 instance_type → 不写 nodeSelector (走 Kueue 自动分, 兼容旧)
        cr = render_hp_pytorch_job_cr(
            name="j", namespace="default", image="pytorch",
            command="python train.py", node_count=1, gpu_per_node=1,
            cpu_per_node_millicores=1000, memory_per_node_mib=1024,
        )
        assert "nodeSelector" not in cr["spec"]["replicaSpecs"][0]["template"]["spec"]


class TestSchemaDefaults:
    """TrainingJobCreate 默认值 = 产品决策 · 防止意外漂移."""

    def test_schema_defaults_match_decision(self) -> None:
        payload = _make_payload()
        assert payload.clean_pod_policy == "All"  # 结束清全部 Pod (前后端默认对齐)
        assert payload.ttl_seconds_after_finished == -1
        assert payload.job_max_retry_count == 0
        assert payload.active_deadline_seconds is None

    def test_schema_rejects_invalid_clean_pod_policy(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _make_payload(clean_pod_policy="Invalid")

    def test_schema_rejects_negative_retry_count(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _make_payload(job_max_retry_count=-1)


class TestSpares:
    """额外节点: spares 要渲进 replicaSpecs, 默认 0。"""

    def _render(self, **overrides) -> dict:
        payload = _make_payload(**overrides)
        return render_hp_pytorch_job_cr(
            name=_job_name(payload),
            namespace="default",
            image=payload.image,
            command=payload.command,
            node_count=payload.node_count,
            spares=payload.spares,
            gpu_per_node=payload.gpu_per_node,
            cpu_per_node_millicores=payload.cpu_per_node_millicores,
            memory_per_node_mib=payload.memory_per_node_mib,
        )

    def test_default_zero(self) -> None:
        """不填 → 0 (与 CRD default 一致, 不改变现有行为)。"""
        cr = self._render()
        assert cr["spec"]["replicaSpecs"][0]["spares"] == 0

    def test_renders_into_replica_spec(self) -> None:
        """填了 → 进 replicaSpecs[0].spares (Kueue 按 replicas + spares 批资源)。"""
        cr = self._render(node_count=2, spares=2)
        rs = cr["spec"]["replicaSpecs"][0]
        assert rs["replicas"] == 2
        assert rs["spares"] == 2

    def test_schema_rejects_negative(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _make_payload(spares=-1)
