"""Orchestration 层单测 · 用 mock adapter + DB · 验证 create 流程拼 CR 正确.

不跑真 DB / K8s · 只断言:
    - create_dev_instance_flow 把 payload 正确转成 CR 调 k8s.create_workspace
    - sync_from_k8s 根据 conditions 正确推 phase
    - build_access_info 根据 phase + ssm_managed_id 正确生成 AccessInfo
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.adapters.k8s import K8sAPIError
from app.modules.devinstance.api.schemas import DevInstanceCreate
from app.modules.devinstance.domain.cr import render_workspace_cr
from app.modules.devinstance.orchestration.create import (
    create_dev_instance_flow,
)
from app.modules.devinstance.response.builders import build_access_info


# ----------------------- helpers -----------------------

def _payload(**overrides) -> DevInstanceCreate:
    base = {
        "name": "my-dev",
        "display_name": "My Dev",
        "description": "hello",
        "template_name": "sagemaker-jupyter-template",
        "image": "public.ecr.aws/sagemaker/sagemaker-distribution:latest-gpu",
        "cpu_request_millicores": 2000,
        "memory_request_mib": 16384,
        "gpu_count": 1,
        "storage_size_gib": 20,
    }
    base.update(overrides)
    return DevInstanceCreate(**base)


def _workspace(
    ws_id: UUID,
    namespace: str = "hyperpod-ns-team-a-nlp",
    fsx_mounts: list[dict] | None = None,
    s3_mounts: list[dict] | None = None,
) -> dict:
    md: dict[str, Any] = {"namespace": namespace}
    if fsx_mounts is not None:
        md["fsx_mounts"] = fsx_mounts
    if s3_mounts is not None:
        md["s3_mounts"] = s3_mounts
    return {
        "id": str(ws_id),
        "namespace": namespace,
        "display_name": "Team A NLP",
        "metadata_json": md,
    }


def _user() -> MagicMock:
    u = MagicMock()
    u.id = uuid4()
    u.is_admin = False
    u.display_name = "alice"
    return u


# ----------------------- create_dev_instance_flow -----------------------

class TestCreateFlow:
    @pytest.mark.asyncio
    async def test_payload_flows_into_workspace_cr(self, monkeypatch):
        """create flow 会按 payload 渲染 CR, 传给 k8s.create_workspace."""
        ws_id = uuid4()
        user = _user()
        payload = _payload(
            gpu_count=2,
            efa_count=2,
            volume_mounts=[
                # 不传 name, 后端按 mount_path slug 自动生成
                {"mount_path": "/shared", "pvc_name": "fsx-pvc"},
            ],
        )

        # Mock ws_crud · ws 必须含跟 payload 匹配的 fsx_mount, 否则校验拒
        ws = _workspace(
            ws_id,
            fsx_mounts=[
                {
                    "mount_path": "/shared",
                    "pvc_name": "fsx-pvc",
                    "filesystem_id": "fs-x",
                    "subdir": "data",
                    "gid": 1000,
                }
            ],
        )
        monkeypatch.setattr(
            "app.modules.devinstance.orchestration.create.ws_crud.get_workspace",
            AsyncMock(return_value=ws),
        )
        # Mock 权限表: 用户被授权 /shared 挂载 (rw)
        monkeypatch.setattr(
            "app.repositories.mount_permissions.list_by_user_in_ws",
            AsyncMock(return_value=[
                {
                    "mount_path": "/shared",
                    "access": "rw",
                    "pvc_name_rw": "fsx-pvc",
                    "pvc_name_ro": "fsx-pvc-ro",
                    "gid": 1000,
                }
            ]),
        )
        # Mock persistence.crud
        monkeypatch.setattr(
            "app.modules.devinstance.orchestration.create.crud.get_by_ws_name",
            AsyncMock(return_value=None),
        )
        created_row = {
            "id": str(uuid4()),
            "name": payload.name,
            "display_name": payload.display_name,
            "workspace_id": ws_id,
        }
        monkeypatch.setattr(
            "app.modules.devinstance.orchestration.create.crud.create",
            AsyncMock(return_value=created_row),
        )

        # Mock K8sClient
        k8s = MagicMock()
        k8s.get_workspace_template = AsyncMock(
            return_value={
                "spec": {
                    "defaultImage": payload.image,
                    "allowedImages": [payload.image],
                    "appType": "jupyterlab",
                },
            }
        )
        k8s.create_workspace = AsyncMock(return_value={})
        k8s.pvc_exists = AsyncMock(return_value=True)

        # Mock db
        db = AsyncMock()

        result = await create_dev_instance_flow(db, k8s, None, ws_id, payload, user)

        assert result == created_row
        # CR 必然调了一次 create_workspace
        assert k8s.create_workspace.await_count == 1
        call_ns, call_cr = k8s.create_workspace.await_args.args
        assert call_ns == ws["namespace"]
        # CR 关键字段
        assert call_cr["apiVersion"] == "workspace.jupyter.org/v1alpha1"
        assert call_cr["kind"] == "Workspace"
        assert call_cr["spec"]["displayName"] == payload.display_name
        assert call_cr["spec"]["templateRef"]["name"] == payload.template_name
        # 资源 request/limit
        assert call_cr["spec"]["resources"]["requests"]["cpu"] == "2000m"
        assert call_cr["spec"]["resources"]["requests"]["memory"] == "16384Mi"
        assert call_cr["spec"]["resources"]["requests"]["nvidia.com/gpu"] == "2"
        # EFA 网卡 (资源模板带出 → CR resources 透传)
        assert call_cr["spec"]["resources"]["requests"]["vpc.amazonaws.com/efa"] == "2"
        assert call_cr["spec"]["resources"]["limits"]["vpc.amazonaws.com/efa"] == "2"
        # 存储
        assert call_cr["spec"]["storage"]["size"] == "20Gi"
        assert call_cr["spec"]["storage"]["mountPath"] == "/home/sagemaker-user"
        # idleShutdown 永远不写 (平台禁用空闲检测)
        assert "idleShutdown" not in call_cr["spec"]
        # 额外卷 · name 后端自动 slug (前端不传 name)
        assert call_cr["spec"]["volumes"][0]["name"] == "vm-shared"
        assert call_cr["spec"]["volumes"][0]["mountPath"] == "/shared"
        assert call_cr["spec"]["volumes"][0]["persistentVolumeClaimName"] == "fsx-pvc"
        # kueue 标签 (Task Governance VAP 强制)
        ns_queue = f"{ws['namespace']}-localqueue"
        assert call_cr["metadata"]["labels"]["kueue.x-k8s.io/queue-name"] == ns_queue
        # 业务追溯 label
        assert call_cr["metadata"]["labels"]["platform.hyperpod.io/workspace-id"] == str(ws_id)

    @pytest.mark.asyncio
    async def test_missing_workspace_raises_404(self, monkeypatch):
        from fastapi import HTTPException
        monkeypatch.setattr(
            "app.modules.devinstance.orchestration.create.ws_crud.get_workspace",
            AsyncMock(return_value=None),
        )
        k8s = MagicMock()
        db = AsyncMock()
        with pytest.raises(HTTPException) as ei:
            await create_dev_instance_flow(
                db, k8s, None, uuid4(), _payload(), _user()
            )
        assert ei.value.status_code == 404

    # 注: 原 test_duplicate_name_raises_409 已删 —— 开发机不再做 name 唯一性检查
    # (CR 名带 10 随机后缀 k8s 层唯一, 与训练一致), 同名不再 409, 该用例语义不成立。

    @pytest.mark.asyncio
    async def test_image_not_in_allowed_raises_400(self, monkeypatch):
        from fastapi import HTTPException
        ws_id = uuid4()
        monkeypatch.setattr(
            "app.modules.devinstance.orchestration.create.ws_crud.get_workspace",
            AsyncMock(return_value=_workspace(ws_id)),
        )
        monkeypatch.setattr(
            "app.modules.devinstance.orchestration.create.crud.get_by_ws_name",
            AsyncMock(return_value=None),
        )
        k8s = MagicMock()
        k8s.get_workspace_template = AsyncMock(
            return_value={"spec": {"allowedImages": ["a:1", "b:2"], "defaultImage": "a:1"}},
        )
        db = AsyncMock()
        with pytest.raises(HTTPException) as ei:
            await create_dev_instance_flow(
                db, k8s, None, ws_id, _payload(image="nope:1"), _user()
            )
        assert ei.value.status_code == 400

    @pytest.mark.asyncio
    async def test_k8s_create_fail_rolls_back_db(self, monkeypatch):
        """k8s.create_workspace 抛异常时, crud.delete 被调清理 DDB row, 500 回给前端."""
        from fastapi import HTTPException
        ws_id = uuid4()
        payload = _payload()
        monkeypatch.setattr(
            "app.modules.devinstance.orchestration.create.ws_crud.get_workspace",
            AsyncMock(return_value=_workspace(ws_id)),
        )
        monkeypatch.setattr(
            "app.repositories.mount_permissions.list_by_user_in_ws",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(
            "app.modules.devinstance.orchestration.create.crud.get_by_ws_name",
            AsyncMock(return_value=None),
        )
        created_row = {"id": str(uuid4())}
        monkeypatch.setattr(
            "app.modules.devinstance.orchestration.create.crud.create",
            AsyncMock(return_value=created_row),
        )
        mock_delete = AsyncMock()
        monkeypatch.setattr(
            "app.modules.devinstance.orchestration.create.crud.delete",
            mock_delete,
        )
        k8s = MagicMock()
        k8s.get_workspace_template = AsyncMock(
            return_value={
                "spec": {
                    "defaultImage": payload.image,
                    "allowedImages": [payload.image],
                    "appType": "jupyterlab",
                },
            }
        )
        k8s.create_workspace = AsyncMock(
            side_effect=K8sAPIError("ApiException.500", "boom")
        )
        db = AsyncMock()
        with pytest.raises(HTTPException) as ei:
            await create_dev_instance_flow(db, k8s, None, ws_id, payload, _user())
        assert ei.value.status_code == 500
        mock_delete.assert_awaited_once_with(None, created_row)

    @pytest.mark.asyncio
    async def test_volume_mount_path_not_on_ws_rejected_400(self, monkeypatch):
        """payload 传 mount_path 不在 ws 列表 → 400."""
        from fastapi import HTTPException
        ws_id = uuid4()
        payload = _payload(volume_mounts=[
            {"mount_path": "/random", "pvc_name": "any-pvc"},
        ])
        # ws 不含任何 mount
        ws = _workspace(ws_id, fsx_mounts=[])
        monkeypatch.setattr(
            "app.modules.devinstance.orchestration.create.ws_crud.get_workspace",
            AsyncMock(return_value=ws),
        )
        # 用户没有任何被授权挂载
        monkeypatch.setattr(
            "app.repositories.mount_permissions.list_by_user_in_ws",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(
            "app.modules.devinstance.orchestration.create.crud.get_by_ws_name",
            AsyncMock(return_value=None),
        )
        # template 校验 mock 让它过
        k8s = MagicMock()
        k8s.get_workspace_template = AsyncMock(return_value={
            "spec": {
                "defaultImage": payload.image,
                "allowedImages": [payload.image],
                "appType": "jupyterlab",
            },
        })
        db = AsyncMock()
        with pytest.raises(HTTPException) as ei:
            await create_dev_instance_flow(db, k8s, None, ws_id, payload, _user())
        assert ei.value.status_code == 400
        assert "/random" in ei.value.detail
        assert "not permitted" in ei.value.detail

    @pytest.mark.asyncio
    async def test_volume_pvc_mismatch_rejected_400(self, monkeypatch):
        """payload 传的 pvc_name 跟 ws 里 mount_path 对应的不一致 → 400."""
        from fastapi import HTTPException
        ws_id = uuid4()
        payload = _payload(volume_mounts=[
            {"mount_path": "/shared", "pvc_name": "wrong-pvc"},
        ])
        ws = _workspace(ws_id)
        monkeypatch.setattr(
            "app.modules.devinstance.orchestration.create.ws_crud.get_workspace",
            AsyncMock(return_value=ws),
        )
        # 用户被授权 /shared → fsx-pvc, 但 payload 传了 wrong-pvc
        monkeypatch.setattr(
            "app.repositories.mount_permissions.list_by_user_in_ws",
            AsyncMock(return_value=[
                {
                    "mount_path": "/shared",
                    "access": "rw",
                    "pvc_name_rw": "fsx-pvc",
                    "pvc_name_ro": "fsx-pvc-ro",
                    "gid": 1000,
                }
            ]),
        )
        monkeypatch.setattr(
            "app.modules.devinstance.orchestration.create.crud.get_by_ws_name",
            AsyncMock(return_value=None),
        )
        k8s = MagicMock()
        k8s.get_workspace_template = AsyncMock(return_value={
            "spec": {
                "defaultImage": payload.image,
                "allowedImages": [payload.image],
                "appType": "jupyterlab",
            },
        })
        db = AsyncMock()
        with pytest.raises(HTTPException) as ei:
            await create_dev_instance_flow(db, k8s, None, ws_id, payload, _user())
        assert ei.value.status_code == 400
        assert "pvc_name mismatch" in ei.value.detail


# ----------------------- build_access_info (纯 · 不用 mock) -----------------------

class TestBuildAccessInfo:
    @staticmethod
    def _k8s(hostname: str | None):
        k8s = MagicMock()
        k8s.get_ssh_service_hostname = AsyncMock(return_value=hostname)
        return k8s

    @pytest.mark.asyncio
    async def test_available_with_hostname_gives_ssh_command(self):
        inst = {
            "id": str(uuid4()),
            "phase": "Available",
            "k8s_namespace": "ns-1",
            "k8s_workspace_name": "ws-1",
        }
        host = "ws-1.ns-1.direct-ssh-e2e.internal"
        ai = await build_access_info(inst, self._k8s(host))
        assert ai.phase == "Available"
        assert ai.ssh_hostname == host
        assert ai.ssh_port == 22222
        assert ai.ssh_command is not None
        assert host in ai.ssh_command and "22222" in ai.ssh_command
        assert ai.ssh_config_snippet is not None and "ProxyCommand" not in ai.ssh_config_snippet
        assert any("authorized_keys" in note for note in ai.notes)
        assert any("EBS" in note for note in ai.notes)

    @pytest.mark.asyncio
    async def test_stopped_no_ssh_command(self):
        inst = {
            "id": str(uuid4()),
            "phase": "Stopped",
            "k8s_namespace": "ns-1",
            "k8s_workspace_name": "ws-1",
        }
        # Stopped: SSH Service 已不在, hostname 读回 None。
        ai = await build_access_info(inst, self._k8s(None))
        assert ai.ssh_command is None
        assert ai.ssh_hostname is None
        assert any("启动" in note for note in ai.notes)

    @pytest.mark.asyncio
    async def test_available_no_hostname_adds_pending_note(self):
        inst = {
            "id": str(uuid4()),
            "phase": "Available",
            "k8s_namespace": "ns-1",
            "k8s_workspace_name": "ws-1",
        }
        ai = await build_access_info(inst, self._k8s(None))
        assert ai.ssh_command is None
        assert any("准备中" in note for note in ai.notes)

    @pytest.mark.asyncio
    async def test_no_k8s_client_degrades_gracefully(self):
        inst = {"id": str(uuid4()), "phase": "Available"}
        ai = await build_access_info(inst)
        assert ai.ssh_hostname is None
        assert ai.ssh_command is None


# ----------------------- domain.cr smoke: workspace CR 依然合规 -----------------------

class TestRenderWorkspaceCrSmoke:
    def test_no_gpu_omits_gpu_keys(self):
        cr = render_workspace_cr(gpu_count=0, kueue_queue_name="q")
        assert "nvidia.com/gpu" not in cr["spec"]["resources"]["requests"]
        assert "nvidia.com/gpu" not in cr["spec"]["resources"]["limits"]

    def test_idle_section_always_omitted(self):
        """平台禁用空闲检测 (容易误停 VSCode Remote-SSH 用户), CR 永不写 idleShutdown."""
        cr = render_workspace_cr(kueue_queue_name="q")
        assert "idleShutdown" not in cr["spec"]

    def test_volumes_rendered_when_given(self):
        cr = render_workspace_cr(
            kueue_queue_name="q",
            volume_mounts=[
                {"name": "fsx", "mount_path": "/shared", "pvc_name": "pvc-a"},
            ],
        )
        assert cr["spec"]["volumes"] == [
            {"name": "fsx", "mountPath": "/shared", "persistentVolumeClaimName": "pvc-a"},
        ]

    def test_volume_name_auto_slug_when_missing(self):
        """前端不传 name, cr 渲染时按 mount_path slug 化."""
        cr = render_workspace_cr(
            kueue_queue_name="q",
            volume_mounts=[
                {"mount_path": "/shared/data", "pvc_name": "fsx-pvc-xx"},
            ],
        )
        v = cr["spec"]["volumes"][0]
        assert v["name"] == "vm-shared-data"
        assert v["mountPath"] == "/shared/data"
        assert v["persistentVolumeClaimName"] == "fsx-pvc-xx"

    def test_volume_name_passthrough_when_provided(self):
        """老开发机 row 已存的 name (本批 PR 之前) 保留, 不被 slug 覆盖."""
        cr = render_workspace_cr(
            kueue_queue_name="q",
            volume_mounts=[
                {"name": "legacy-name", "mount_path": "/x", "pvc_name": "pvc-x"},
            ],
        )
        assert cr["spec"]["volumes"][0]["name"] == "legacy-name"

    def test_security_context_omitted_when_no_fsx(self):
        """没挂 FSx 时不写 podSecurityContext / containerSecurityContext, 走 template default."""
        cr = render_workspace_cr(kueue_queue_name="q")
        assert "podSecurityContext" not in cr["spec"]
        assert "containerSecurityContext" not in cr["spec"]

    def test_security_context_with_primary_gid(self):
        """ws 挂 FSx 时, runAsGroup 放主容器, fsGroup/supplementalGroups 放 Pod 级."""
        cr = render_workspace_cr(kueue_queue_name="q", primary_gid=2001)
        # 容器级 (只主容器, 不影响 sidecar) - 切 gid 让 sagemaker-user 能写 FSx subdir
        csc = cr["spec"]["containerSecurityContext"]
        assert csc["runAsUser"] == 1000
        assert csc["runAsGroup"] == 2001
        # Pod 级 - fsGroup 必须 Pod 级才能让 K8s chown 卷
        psc = cr["spec"]["podSecurityContext"]
        assert psc["fsGroup"] == 2001
        assert psc["supplementalGroups"] == [2001]
        assert "runAsUser" not in psc  # sidecar 必须 root 跑, 不能 Pod 级 runAsUser
        assert "runAsGroup" not in psc

    def test_priority_class_label_rendered(self):
        """priority_class 传入 → CR metadata.labels 加 kueue priority-class."""
        cr = render_workspace_cr(
            kueue_queue_name="q", priority_class="devinstance-default"
        )
        labels = cr["metadata"]["labels"]
        assert labels["kueue.x-k8s.io/priority-class"] == "devinstance-default"

    def test_priority_class_omitted_when_none(self):
        cr = render_workspace_cr(kueue_queue_name="q")
        assert "kueue.x-k8s.io/priority-class" not in cr["metadata"]["labels"]

    def test_security_context_primary_gid_and_supplemental(self):
        """跨 team: runAsGroup=primary, supplementalGroups 去重排序含所有挂载 gid."""
        cr = render_workspace_cr(
            kueue_queue_name="q",
            primary_gid=5003,
            supplemental_gids=[5001, 5003, 5002],
        )
        spec = cr["spec"]
        assert spec["containerSecurityContext"]["runAsGroup"] == 5003
        assert spec["containerSecurityContext"]["runAsUser"] == 1000
        assert spec["podSecurityContext"]["supplementalGroups"] == [5001, 5002, 5003]
        assert spec["podSecurityContext"]["fsGroup"] == 5003

    def test_volume_sub_path_rendered_for_fsx(self):
        """FSx mount 渲染 spec.volumes[i].subPath (隔离多租户子目录)."""
        cr = render_workspace_cr(
            kueue_queue_name="q",
            volume_mounts=[
                {
                    "mount_path": "/fsx/team-a",
                    "pvc_name": "fsx-pvc",
                    "sub_path": "team-a",
                },
            ],
        )
        v = cr["spec"]["volumes"][0]
        assert v["mountPath"] == "/fsx/team-a"
        assert v["subPath"] == "team-a"

    def test_volume_no_sub_path_for_s3(self):
        """S3 PV 用 prefix 圈定, mount 不写 subPath."""
        cr = render_workspace_cr(
            kueue_queue_name="q",
            volume_mounts=[
                {"mount_path": "/s3/data", "pvc_name": "s3-pvc", "sub_path": None},
            ],
        )
        v = cr["spec"]["volumes"][0]
        assert "subPath" not in v

    def test_health_affinity_always_required(self):
        """无论传不传 preferred IG, 都加 health required (只调度到 Schedulable 节点)."""
        cr = render_workspace_cr(kueue_queue_name="q")
        na = cr["spec"]["affinity"]["nodeAffinity"]
        terms = na["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"]
        expr = terms[0]["matchExpressions"][0]
        assert expr["key"] == "sagemaker.amazonaws.com/node-health-status"
        assert expr["operator"] == "In"
        assert expr["values"] == ["Schedulable"]

    def test_no_preferred_ig_when_empty(self):
        """没传 CPU IG (如 GPU 开发机) → 不渲染 preferred, 只 health required."""
        cr = render_workspace_cr(kueue_queue_name="q")
        na = cr["spec"]["affinity"]["nodeAffinity"]
        assert "preferredDuringSchedulingIgnoredDuringExecution" not in na

    def test_preferred_ig_soft_affinity_rendered(self):
        """CPU 开发机: 传 CPU IG 名 → 软优先 (weight=100, instance-group-name In)."""
        cr = render_workspace_cr(
            kueue_queue_name="q",
            preferred_instance_groups=["m5-2x", "cpu-pool"],
        )
        na = cr["spec"]["affinity"]["nodeAffinity"]
        pref = na["preferredDuringSchedulingIgnoredDuringExecution"]
        assert len(pref) == 1
        assert pref[0]["weight"] == 100
        expr = pref[0]["preference"]["matchExpressions"][0]
        assert expr["key"] == "sagemaker.amazonaws.com/instance-group-name"
        assert expr["operator"] == "In"
        assert expr["values"] == ["m5-2x", "cpu-pool"]
        # 软优先共存 health required (硬过滤仍在)
        assert "requiredDuringSchedulingIgnoredDuringExecution" in na


@pytest.mark.asyncio
async def test_assert_instance_type_allowed_rejects_unlisted():
    """instance_type 不在 ws 配额 → 403; 在 → 通过。"""
    from unittest.mock import patch

    from fastapi import HTTPException

    from app.modules.devinstance.orchestration.create import (
        _assert_instance_type_allowed,
    )

    class _Q:
        def __init__(self, types):
            self.resources = [
                type("R", (), {"instance_type": t})() for t in types
            ]

    with patch(
        "app.modules.devinstance.orchestration.create.get_workspace_quota",
        AsyncMock(return_value=_Q(["ml.g6.12xlarge"])),
    ):
        # 在配额内 → 不抛
        await _assert_instance_type_allowed(None, "ws-1", "ml.g6.12xlarge")
        # 不在配额 → 403
        with pytest.raises(HTTPException) as ei:
            await _assert_instance_type_allowed(None, "ws-1", "ml.m5.4xlarge")
        assert ei.value.status_code == 403
