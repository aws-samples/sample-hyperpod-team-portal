"""Export OpenAPI 3.1 schema as static JSON for frontend codegen.

Usage:
    python scripts/export_openapi.py [--out openapi.json]

Why static export instead of `curl http://localhost:8000/openapi.json`:
- 不需要启 server (CI 友好)
- 不需要连 DB (lifespan 不跑)
- 输出稳定: keys 排序后写入, diff 只反映真实 schema 变化

输出契约:
- 默认写到 services/platform-api/openapi.json (相对调用脚本所在仓库根)
- 写成 utf-8 + 缩进 2 + sort_keys=True 三件套, 保证 git diff 干净
- exit code 0 = 成功, 非 0 = 导入失败
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def export(out_path: Path) -> None:
    # Defer import 避免顶层副作用 (logging / DB engine 还没必要)
    from app.main import app

    schema = app.openapi()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    paths = len(schema.get("paths", {}))
    components = len(schema.get("components", {}).get("schemas", {}))
    print(f"openapi exported: {out_path} ({paths} paths · {components} schemas)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export OpenAPI schema")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "openapi.json",
        help="output path (default: services/platform-api/openapi.json)",
    )
    args = parser.parse_args()
    try:
        export(args.out)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
