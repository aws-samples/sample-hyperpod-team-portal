"""log_streams 字段 crud 读写对称 (防 create 整行 put 抹掉)。"""
from app.modules.inference.persistence import crud


def test_inf_to_md_includes_log_streams():
    streams = [{"stream_name": "s1", "pod_short": "abc", "seq": 1, "first_ts": 100, "last_ts": 200}]
    md = crud._inf_to_md({"name": "ep1", "log_streams": streams})
    assert md["log_streams"] == streams


def test_ri_to_inf_roundtrip_log_streams():
    streams = [{"stream_name": "s1", "pod_short": "abc", "seq": 1, "first_ts": 100, "last_ts": 200}]
    item = {"resource_id": "i1", "workspace_id": "ws-1", "metadata": crud._inf_to_md({"name": "ep1", "log_streams": streams})}
    out = crud._ri_to_inf(item)
    assert out["log_streams"] == streams


def test_inf_to_md_omits_log_streams_when_absent():
    md = crud._inf_to_md({"name": "ep1"})
    assert "log_streams" not in md
