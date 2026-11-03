"""domain/validators.py 的单元测试 (纯函数, 无 IO)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.devinstance.api.schemas import (
    DevInstanceCreate,
    TemplateCreate,
    VolumeMount,
)
from app.modules.devinstance.domain.validators import (
    parse_cpu_millicores,
    parse_gib,
    parse_memory_mib,
    parse_pvc_capacity_gib,
)


# ---------- parse_gib ----------

class TestParseGib:
    def test_gi(self) -> None:
        assert parse_gib("10Gi") == 10

    def test_ti(self) -> None:
        assert parse_gib("2Ti") == 2048

    def test_unknown_unit_returns_fallback(self) -> None:
        assert parse_gib("500Mi", fallback=5) == 5

    def test_garbage_returns_fallback(self) -> None:
        assert parse_gib("abc", fallback=7) == 7

    def test_empty_returns_fallback(self) -> None:
        assert parse_gib("", fallback=3) == 3


# ---------- parse_cpu_millicores ----------

class TestParseCpuMillicores:
    def test_millicores(self) -> None:
        assert parse_cpu_millicores("500m") == 500

    def test_integer_cores(self) -> None:
        assert parse_cpu_millicores("2") == 2000

    def test_fractional_cores(self) -> None:
        assert parse_cpu_millicores("2.5") == 2500

    def test_garbage_returns_2000(self) -> None:
        assert parse_cpu_millicores("not-a-number") == 2000


# ---------- parse_memory_mib ----------

class TestParseMemoryMib:
    def test_gi(self) -> None:
        assert parse_memory_mib("8Gi") == 8192

    def test_mi(self) -> None:
        assert parse_memory_mib("1024Mi") == 1024

    def test_unknown_returns_8192(self) -> None:
        assert parse_memory_mib("500Ki") == 8192

    def test_garbage_returns_8192(self) -> None:
        assert parse_memory_mib("oops") == 8192


# ---------- parse_pvc_capacity_gib ----------

class TestParsePvcCapacityGib:
    def test_gi(self) -> None:
        assert parse_pvc_capacity_gib({"storage": "100Gi"}) == 100

    def test_ti(self) -> None:
        assert parse_pvc_capacity_gib({"storage": "1Ti"}) == 1024

    def test_mi_rounds_to_min_1(self) -> None:
        assert parse_pvc_capacity_gib({"storage": "500Mi"}) == 1  # 500/1024=0, max(1, 0)=1

    def test_none_input(self) -> None:
        assert parse_pvc_capacity_gib(None) is None

    def test_empty_dict(self) -> None:
        assert parse_pvc_capacity_gib({}) is None

    def test_no_storage_key(self) -> None:
        assert parse_pvc_capacity_gib({"other": "10Gi"}) is None

    def test_invalid_format(self) -> None:
        assert parse_pvc_capacity_gib({"storage": "badvalue"}) is None


# ---------- Pydantic field_validator ----------

class TestVolumeMountReservedName:
    def test_workspace_storage_rejected(self) -> None:
        with pytest.raises(ValidationError, match="workspace-storage"):
            VolumeMount(
                name="workspace-storage",
                mount_path="/shared",
                pvc_name="some-pvc",
            )

    def test_normal_name_ok(self) -> None:
        vm = VolumeMount(
            name="shared-fsx",
            mount_path="/shared",
            pvc_name="team-pvc",
        )
        assert vm.name == "shared-fsx"


class TestVolumeMountPrimaryMount:
    @pytest.mark.parametrize(
        "bad_path",
        [
            "/home/sagemaker-user",
            "/home/sagemaker-user/",
            "/home/jovyan",
            "/home/jovyan/",
        ],
    )
    def test_primary_path_rejected(self, bad_path: str) -> None:
        with pytest.raises(ValidationError, match="primaryStorage"):
            VolumeMount(
                name="shared-fsx", mount_path=bad_path, pvc_name="team-pvc"
            )

    def test_normal_path_ok(self) -> None:
        vm = VolumeMount(
            name="shared-fsx",
            mount_path="/shared/datasets",
            pvc_name="team-pvc",
        )
        assert vm.mount_path == "/shared/datasets"


class TestDevInstanceCreateMemoryPolicy:
    def test_below_8gi_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DevInstanceCreate(
                name="my-dev",
                display_name="My Dev",
                memory_request_mib=4096,  # 4Gi < 8Gi
            )

    def test_exactly_8gi_ok(self) -> None:
        m = DevInstanceCreate(
            name="my-dev", display_name="My Dev", memory_request_mib=8192
        )
        assert m.memory_request_mib == 8192


class TestTemplateCreateDefaultImage:
    def test_default_not_in_allowed_rejected(self) -> None:
        with pytest.raises(ValidationError, match="allowed_images"):
            TemplateCreate(
                name="my-tpl",
                display_name="My Template",
                app_type="jupyterlab",
                default_image="missing-image:1.0",
                allowed_images=["a:1.0", "b:2.0"],
            )

    def test_default_in_allowed_ok(self) -> None:
        t = TemplateCreate(
            name="my-tpl",
            display_name="My Template",
            app_type="jupyterlab",
            default_image="a:1.0",
            allowed_images=["a:1.0", "b:2.0"],
        )
        assert t.default_image == "a:1.0"
