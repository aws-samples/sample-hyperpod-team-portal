from app.adapters.k8s.workspace_resources import (
    fsx_pv_name,
    fsx_pvc_name,
)


def test_fsx_pv_name_rw_suffix():
    assert fsx_pv_name("ws1", "data", access="rw") == "pv-ws-ws1-fsx-data-rw"


def test_fsx_pv_name_ro_suffix():
    assert fsx_pv_name("ws1", "data", access="ro") == "pv-ws-ws1-fsx-data-ro"


def test_fsx_pvc_name_rw_suffix():
    assert fsx_pvc_name("data", access="rw") == "pvc-ws-fsx-data-rw"


def test_fsx_pvc_name_ro_suffix():
    assert fsx_pvc_name("data", access="ro") == "pvc-ws-fsx-data-ro"
