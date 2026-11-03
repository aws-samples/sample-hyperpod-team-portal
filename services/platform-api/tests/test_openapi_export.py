"""OpenAPI 契约稳定性 gate · P0-1 守门测试.

目的:
1. 防止后端 schema 改动后忘记 `make api-sync`
2. 防止 operationId 重复 (FastAPI Duplicate Operation ID 警告)
3. 防止 schema.gen.ts 与 openapi.json 漂移

CI 行为:
- 改了 Pydantic schema 必跑 `make api-sync` 并 commit 两个文件
- 不一致直接 fail, 给清晰错误信息
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2].parent
OPENAPI_JSON = REPO_ROOT / "services" / "platform-api" / "openapi.json"
SCHEMA_GEN_TS = REPO_ROOT / "frontend" / "src" / "shared" / "api" / "schema.gen.ts"


def test_openapi_json_exists() -> None:
    assert OPENAPI_JSON.exists(), (
        f"openapi.json 缺失. 跑 `make api-export` 重新生成. 期望路径: {OPENAPI_JSON}"
    )


def test_openapi_json_valid_structure() -> None:
    schema = json.loads(OPENAPI_JSON.read_text())
    assert "openapi" in schema
    assert "paths" in schema and len(schema["paths"]) > 0
    assert "components" in schema
    assert "schemas" in schema["components"]


def test_no_duplicate_operation_ids() -> None:
    """FastAPI Duplicate Operation ID -> openapi-typescript 生成重复 identifier."""
    schema = json.loads(OPENAPI_JSON.read_text())
    seen: dict[str, str] = {}
    duplicates: list[tuple[str, str, str]] = []
    for path, ops in schema["paths"].items():
        for method, op in ops.items():
            if not isinstance(op, dict):
                continue
            op_id = op.get("operationId")
            if op_id is None:
                continue
            if op_id in seen:
                duplicates.append((op_id, seen[op_id], f"{method.upper()} {path}"))
            else:
                seen[op_id] = f"{method.upper()} {path}"
    assert not duplicates, (
        "重复 operationId (会让 openapi-typescript 生成 duplicate identifier):\n"
        + "\n".join(f"  {op_id}: {a} vs {b}" for op_id, a, b in duplicates)
    )


def test_app_openapi_clean_no_warnings() -> None:
    """`app.openapi()` 调用本身不抛 FastAPI Duplicate Operation ID 警告."""
    from app.main import app

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        app.openapi_schema = None
        app.openapi()
        relevant = [
            w for w in caught if "Duplicate Operation ID" in str(w.message)
        ]
        assert not relevant, (
            "FastAPI 报 Duplicate Operation ID 警告:\n"
            + "\n".join(f"  {w.message}" for w in relevant)
        )


@pytest.mark.skipif(
    not SCHEMA_GEN_TS.exists(),
    reason="schema.gen.ts 不存在 (前端尚未跑 pnpm gen:api)",
)
def test_schema_gen_ts_contains_sample_schemas() -> None:
    """抽样检查: openapi.json 头中尾各 1 个 schema 名应在 schema.gen.ts 中.

    完整字节级 diff 由 CI `make api-check` 负责.
    """
    schema = json.loads(OPENAPI_JSON.read_text())
    schema_names = list(schema["components"]["schemas"].keys())
    if not schema_names:
        pytest.skip("openapi 无 schema 可校验")
    ts_text = SCHEMA_GEN_TS.read_text()
    samples = [schema_names[0], schema_names[len(schema_names) // 2], schema_names[-1]]
    for name in samples:
        assert name in ts_text, (
            f"schema 「{name}」在 openapi.json 但不在 schema.gen.ts. "
            f"请跑 `make api-sync`."
        )
