"""RayJob CR 渲染测试 · 锁实测坐实的 4 条配方 (缺一跑不通)。"""

from __future__ import annotations

from app.modules.rayjob.domain.cr import render_rayjob_cr


def _render(**overrides):
    base = dict(
        name="ray-x", namespace="ns-a", rayjob_id="rid", workspace_id="wid",
        creator_id="cid",
        extra_fsx_mounts=[{"pvc_name": "pvc-a", "mount_path": "/fsx/team-a-data", "read_only": False, "gid": 5001}],
        entry_script_path="bash /fsx/team-a-data/run.sh",
        head_instance_type="ml.m5.4xlarge", head_gpu=0,
        worker_instance_type="ml.g6.12xlarge",
    )
    base.update(overrides)
    return render_rayjob_cr(**base)


class TestRayJobRecipe:
    """实测 4 条配方: 两层 queue-name / HTTPMode / shutdown true / root+挂载点."""

    def test_queue_name_two_layers(self) -> None:
        # ★第一层 metadata + 第二层 head/worker pod template 都要 queue-name
        cr = _render()
        q = "ns-a-localqueue"
        assert cr["metadata"]["labels"]["kueue.x-k8s.io/queue-name"] == q
        head = cr["spec"]["rayClusterSpec"]["headGroupSpec"]["template"]
        worker = cr["spec"]["rayClusterSpec"]["workerGroupSpecs"][0]["template"]
        assert head["metadata"]["labels"]["kueue.x-k8s.io/queue-name"] == q
        assert worker["metadata"]["labels"]["kueue.x-k8s.io/queue-name"] == q

    def test_http_mode(self) -> None:
        # ★submissionMode HTTPMode 消掉 submitter Job VAP 拦点
        assert _render()["spec"]["submissionMode"] == "HTTPMode"

    def test_shutdown_after_finish_true(self) -> None:
        # ★Kueue webhook 强制 true
        assert _render()["spec"]["shutdownAfterJobFinishes"] is True

    def test_run_as_root_reads_fsx(self) -> None:
        head = _render()["spec"]["rayClusterSpec"]["headGroupSpec"]["template"]["spec"]
        sc = head["securityContext"]
        assert sc["runAsUser"] == 0 and sc["runAsGroup"] == 0
        # 选中 FSx gid (5001) 进 supplementalGroups (root 读授权盘)
        assert 5001 in sc["supplementalGroups"]

    def test_no_security_context_when_not_root(self) -> None:
        head = _render(run_as_root=False)["spec"]["rayClusterSpec"][
            "headGroupSpec"]["template"]["spec"]
        assert "securityContext" not in head

    def test_fsx_mount_follows_authorized_path(self) -> None:
        # ★挂载点用授权 mount_path (照训练多盘全平等; /023)
        cr = _render(extra_fsx_mounts=[
            {"pvc_name": "pvc-x", "mount_path": "/fsx/team-c-training-data", "read_only": True, "gid": 5002},
        ])
        head = cr["spec"]["rayClusterSpec"]["headGroupSpec"]["template"]["spec"]
        by_path = {m["mountPath"]: m for m in head["containers"][0]["volumeMounts"]}
        assert by_path["/fsx/team-c-training-data"]["readOnly"] is True

    def test_head_driver_log_sidecar(self) -> None:
        # head 加 driver-log sidecar 导训练输出到 CloudWatch; worker 不加
        cr = _render()
        head = cr["spec"]["rayClusterSpec"]["headGroupSpec"]["template"]["spec"]
        worker = cr["spec"]["rayClusterSpec"]["workerGroupSpecs"][0]["template"]["spec"]
        # head: ray-head 仍是 containers[0], sidecar 追加在后
        names = [c["name"] for c in head["containers"]]
        assert names[0] == "ray-head"
        assert "driver-log-tailer" in names
        # head: 共享 emptyDir + ray-head 挂 /tmp/ray
        assert any(v["name"] == "ray-driver-logs" and "emptyDir" in v for v in head["volumes"])
        assert "/tmp/ray" in {m["mountPath"] for m in head["containers"][0]["volumeMounts"]}
        # ★worker 不被污染 (volumes/mounts 是共享 list, copy 才对): 无 sidecar / 无该卷 / 无 /tmp/ray
        assert "driver-log-tailer" not in [c["name"] for c in worker["containers"]]
        assert all(v["name"] != "ray-driver-logs" for v in worker["volumes"])
        assert "/tmp/ray" not in {m["mountPath"] for m in worker["containers"][0]["volumeMounts"]}

    def test_s3_dataset_mount(self) -> None:
        cr = _render(s3_datasets=[
            {"bucket": "b", "prefix": "", "mount_path": "/s3/data", "pvc_name": "pvc-ws-s3-x"},
        ])
        head = cr["spec"]["rayClusterSpec"]["headGroupSpec"]["template"]["spec"]
        by_path = {m["mountPath"]: m for m in head["containers"][0]["volumeMounts"]}
        assert by_path["/s3/data"]["readOnly"] is True
        vols = {v["name"]: v for v in head["volumes"]}
        assert any(v.get("persistentVolumeClaim", {}).get("claimName") == "pvc-ws-s3-x" for v in vols.values())

    def test_fixed_replicas_no_autoscaling(self) -> None:
        wg = _render(worker_replicas=3)["spec"]["rayClusterSpec"]["workerGroupSpecs"][0]
        assert wg["replicas"] == wg["minReplicas"] == wg["maxReplicas"] == 3

    def test_entrypoint_verbatim(self) -> None:
        # entrypoint 原样用用户填的完整命令 (不硬加 bash, 防双前缀 exit 126)
        cr = _render(entry_script_path="bash /fsx/proj/train.sh")
        assert cr["spec"]["entrypoint"] == "bash /fsx/proj/train.sh"
        cr2 = _render(entry_script_path="python /fsx/proj/main.py")
        assert cr2["spec"]["entrypoint"] == "python /fsx/proj/main.py"

    def test_gpu_and_efa_resources(self) -> None:
        cr = _render(gpu_per_node=2, efa_per_node=1)
        wc = cr["spec"]["rayClusterSpec"]["workerGroupSpecs"][0]["template"][
            "spec"]["containers"][0]
        assert wc["resources"]["limits"]["nvidia.com/gpu"] == "2"
        assert wc["resources"]["limits"]["vpc.amazonaws.com/efa"] == "1"

    def test_no_efa_when_zero(self) -> None:
        wc = _render(efa_per_node=0)["spec"]["rayClusterSpec"]["workerGroupSpecs"][0][
            "template"]["spec"]["containers"][0]
        assert "vpc.amazonaws.com/efa" not in wc["resources"]["limits"]

    def test_env_secret_ref_no_plaintext(self) -> None:
        cr = _render(env_secrets=[
            {"name": "TOKEN", "secret_ref": "alice-secrets", "secret_key": "TOKEN"}
        ])
        envs = cr["spec"]["rayClusterSpec"]["headGroupSpec"]["template"]["spec"][
            "containers"][0]["env"]
        tok = next(e for e in envs if e["name"] == "TOKEN")
        assert "value" not in tok
        assert tok["valueFrom"]["secretKeyRef"] == {
            "name": "alice-secrets", "key": "TOKEN"
        }

    def test_platform_labels(self) -> None:
        labels = _render()["metadata"]["labels"]
        assert labels["platform.hyperpod.io/rayjob-id"] == "rid"
        assert labels["platform.hyperpod.io/workspace-id"] == "wid"

    def test_apiversion_kind(self) -> None:
        cr = _render()
        assert cr["apiVersion"] == "ray.io/v1"
        assert cr["kind"] == "RayJob"

    def test_plain_env_rendered(self) -> None:
        # 普通 env dict → 容器 env (与 _COMM_ENV / secretKeyRef 并存)
        cr = _render(env={"WANDB_PROJECT": "demo"})
        envs = cr["spec"]["rayClusterSpec"]["headGroupSpec"]["template"]["spec"][
            "containers"][0]["env"]
        wandb = next(e for e in envs if e["name"] == "WANDB_PROJECT")
        assert wandb["value"] == "demo"

    def test_head_worker_split_instance_type(self) -> None:
        # ★head 落 CPU 机型省 GPU, worker 落 GPU 机型 (各自 nodeSelector)
        cr = _render(
            head_instance_type="ml.m5.4xlarge", head_gpu=0,
            worker_instance_type="ml.g6.12xlarge", gpu_per_node=4,
        )
        head = cr["spec"]["rayClusterSpec"]["headGroupSpec"]["template"]["spec"]
        worker = cr["spec"]["rayClusterSpec"]["workerGroupSpecs"][0]["template"]["spec"]
        assert head["nodeSelector"]["node.kubernetes.io/instance-type"] == "ml.m5.4xlarge"
        assert worker["nodeSelector"]["node.kubernetes.io/instance-type"] == "ml.g6.12xlarge"
        # head 0 GPU (省卡), worker 4 GPU
        assert head["containers"][0]["resources"]["limits"]["nvidia.com/gpu"] == "0"
        assert worker["containers"][0]["resources"]["limits"]["nvidia.com/gpu"] == "4"

    def test_head_worker_split_image(self) -> None:
        # ★head CPU 镜像 (落 CPU node 无驱动, gpu 镜像 NVML 崩), worker gpu 镜像
        cr = _render(head_image="rayproject/ray:2.9.0", worker_image="rayproject/ray:2.9.0-gpu")
        head = cr["spec"]["rayClusterSpec"]["headGroupSpec"]["template"]["spec"]
        worker = cr["spec"]["rayClusterSpec"]["workerGroupSpecs"][0]["template"]["spec"]
        assert head["containers"][0]["image"] == "rayproject/ray:2.9.0"
        assert worker["containers"][0]["image"] == "rayproject/ray:2.9.0-gpu"

    def test_run_policy_fields(self) -> None:
        # Ray 运行策略平铺字段 (非 PyTorchJob runPolicy 嵌套)
        cr = _render(ttl_seconds_after_finished=600, backoff_limit=2)
        assert cr["spec"]["ttlSecondsAfterFinished"] == 600
        assert cr["spec"]["backoffLimit"] == 2
        assert cr["spec"]["activeDeadlineSeconds"] == 24 * 3600
