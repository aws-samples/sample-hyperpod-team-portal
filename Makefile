.PHONY: help api-export api-types api-sync api-check test-backend check-imports check-i18n

help:
	@echo "HyperPod Platform · 仓库根 Makefile"
	@echo ""
	@echo "  make api-export   导出 services/platform-api/openapi.json (静态 schema)"
	@echo "  make api-types    从 openapi.json 生成 frontend/src/shared/api/schema.gen.ts"
	@echo "  make api-sync     api-export + api-types 一把梭 (改了 Pydantic schema 必跑)"
	@echo "  make api-check    校验 schema.gen.ts 与 openapi.json 同步 (CI gate)"
	@echo "  make test-backend pytest -q services/platform-api/"
	@echo "  make check-imports frontend 前端 import 路径合规守门 (Wave 5 P0-4)"
	@echo "  make check-i18n   前后端 i18n 守门 (无硬编码中文 + 中英文案表一致) + i18n pytest 子集"
	@echo ""

api-export:
	cd services/platform-api && python scripts/export_openapi.py

api-types:
	cd frontend && pnpm gen:api

api-sync: api-export api-types
	@echo "✅ openapi schema + frontend types 已同步"

api-check:
	cd frontend && pnpm check:api

test-backend:
	cd services/platform-api && python -m pytest -q

check-imports:
	cd frontend && pnpm check:imports

check-i18n:
	cd frontend && pnpm check:i18n
	cd services/platform-api && python3 scripts/check_i18n.py
	cd services/platform-api && .venv/bin/python -m pytest -q -p no:cacheprovider app/core/tests app/modules/monitoring/tests/test_template_i18n.py
