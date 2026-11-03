"""资源模板 service + schema 测试 (统一一套, 仅 admin 管).

覆盖:
    - schema 统一校验 (TemplateResource 单值, req=lim; 边界拒绝)
    - SK 编码 (tpl#<id>, 无 type/scope)
    - 权限: 增删改需 ws admin; 列表全员可见
    - seed 默认模板 (统一一套)
用 monkeypatch mock repo + ws_crud, 不碰真 DDB。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.adapters.ddb import tables
from app.modules.resource_templates.api.schemas import (
    TemplateCreate,
    TemplateResource,
)
from app.modules.resource_templates.orchestration import service


# ---------- schema ----------

class TestSchema:
    def test_template_resource_ok(self) -> None:
        r = TemplateResource(gpu=2, cpu_cores=8, mem_gib=32)
        assert r.gpu == 2 and r.cpu_cores == 8 and r.mem_gib == 32

    def test_gpu_over_limit_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TemplateResource(gpu=99, cpu_cores=4, mem_gib=16)

    def test_cpu_zero_rejected(self) -> None:
        # cpu/mem 不设上限 (大机型 B300); 仍卡 >0 下限。
        with pytest.raises(ValidationError):
            TemplateResource(gpu=1, cpu_cores=0, mem_gib=16)

    def test_large_cpu_mem_ok(self) -> None:
        # B300 等大机型: 几百核 + TB 内存, 不再被上限拦。
        TemplateResource(gpu=8, cpu_cores=288, mem_gib=2048)


# ---------- SK 编码 ----------

class TestSortKey:
    def test_key(self) -> None:
        assert tables.res_tpl_key("abc") == "tpl#abc"

    def test_prefix(self) -> None:
        assert tables.res_tpl_prefix() == "tpl#"
        assert tables.res_tpl_key("x").startswith(tables.res_tpl_prefix())


# ---------- _validate_resource ----------

class TestValidateResource:
    def test_unified_single_value(self) -> None:
        out = service._validate_resource({"gpu": 1, "cpu_cores": 8, "mem_gib": 32})
        assert out["cpu_cores"] == 8 and out["mem_gib"] == 32

    def test_legacy_reqlim_rejected(self) -> None:
        # 旧 req/lim 字段缺统一必填项 cpu_cores/mem_gib → 校验失败
        with pytest.raises(ValidationError):
            service._validate_resource(
                {"gpu": 1, "cpu_req_cores": 4, "cpu_lim_cores": 8,
                 "mem_req_gib": 16, "mem_lim_gib": 32},
            )


# ---------- 权限 + 写 (mock repo) ----------

class _FakeRepo:
    """内存版 repo, 按 (ws, sort_key) 存。"""

    def __init__(self) -> None:
        self.store: dict[tuple, dict] = {}

    async def get(self, ws, sk):
        return self.store.get((ws, sk))

    async def put(self, *, workspace_id, sort_key, item_fields):
        row = {"workspace_id": workspace_id, "sort_key": sort_key,
               "created_at": "t0", "updated_at": "t1", **item_fields}
        self.store[(workspace_id, sort_key)] = row
        return row

    async def delete(self, ws, sk):
        self.store.pop((ws, sk), None)

    async def list_all(self, ws):
        p = tables.res_tpl_prefix()
        return [v for (w, sk), v in self.store.items() if w == ws and sk.startswith(p)]


@pytest.fixture
def fake_repo(monkeypatch):
    fake = _FakeRepo()
    monkeypatch.setattr(service, "repo", fake)
    return fake


def _mock_admin(monkeypatch, is_admin: bool):
    async def fake_membership(db, ws, user):
        return {"role": "admin" if is_admin else "member"}
    monkeypatch.setattr(service.ws_crud, "get_membership", fake_membership)


@pytest.mark.asyncio
class TestServiceWrite:
    async def test_admin_create_ok(self, fake_repo, monkeypatch):
        _mock_admin(monkeypatch, is_admin=True)
        user = {"user_id": "admin", "is_admin": True}
        payload = TemplateCreate(
            name="中规格", resource={"gpu": 2, "cpu_cores": 8, "mem_gib": 32},
        )
        item = await service.create_template("ws1", payload, user)
        assert item["name"] == "中规格"
        assert item["resource"]["cpu_cores"] == 8
        assert item["creator_username"] == "admin"

    async def test_non_admin_create_rejected(self, fake_repo, monkeypatch):
        _mock_admin(monkeypatch, is_admin=False)
        user = {"user_id": "bob", "is_admin": False}
        payload = TemplateCreate(
            name="x", resource={"gpu": 1, "cpu_cores": 4, "mem_gib": 16},
        )
        with pytest.raises(Exception) as exc:
            await service.create_template("ws1", payload, user)
        assert "403" in str(exc.value) or "管理员" in str(exc.value)

    async def test_non_member_rejected(self, fake_repo, monkeypatch):
        async def no_member(db, ws, u):
            return None
        monkeypatch.setattr(service.ws_crud, "get_membership", no_member)
        user = {"user_id": "stranger", "is_admin": False}
        payload = TemplateCreate(
            name="x", resource={"gpu": 1, "cpu_cores": 4, "mem_gib": 16},
        )
        with pytest.raises(Exception) as exc:
            await service.create_template("ws1", payload, user)
        assert "403" in str(exc.value) or "成员" in str(exc.value)

    async def test_non_admin_delete_rejected(self, fake_repo, monkeypatch):
        _mock_admin(monkeypatch, is_admin=False)
        user = {"user_id": "bob", "is_admin": False}
        with pytest.raises(Exception) as exc:
            await service.delete_template("ws1", "abc", user)
        assert "403" in str(exc.value) or "管理员" in str(exc.value)

    async def test_member_list_sees_seeded(self, fake_repo, monkeypatch):
        _mock_admin(monkeypatch, is_admin=False)
        lst = await service.list_templates("ws9", {"user_id": "u", "is_admin": False})
        # seed 了 4 个统一档
        assert len(lst) == 4
        assert any(t["name"] == "中规格" for t in lst)
