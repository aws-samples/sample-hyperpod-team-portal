"""submit_build 流程测试 (mock 所有 adapter + repo)。"""


async def test_submit_build_flow(monkeypatch):
    from app.modules.registry.orchestration import builds
    from app.modules.registry.api.schemas import SubmitBuildBody

    async def ok_member(ws, u):
        return None

    monkeypatch.setattr(builds, "_require_ws_member", ok_member)
    monkeypatch.setattr(builds, "_username", lambda u: "tester")

    async def fake_ensure(name, **k):
        return f"111.dkr.ecr.us-west-2.amazonaws.com/{name}"

    async def fake_put_bytes(b, k, d):
        assert d[:2] == b"PK"  # zip magic number

    async def fake_start(**kw):
        assert kw["compute_type"] == "BUILD_GENERAL1_LARGE"
        assert kw["image_tag"] == "1.0"
        return "proj:abc"

    captured = {}

    async def fake_repo_put(*, workspace_id, sort_key, item_fields):
        captured.update(item_fields)
        captured["sk"] = sort_key
        return {"created_at": "t", **item_fields}

    monkeypatch.setattr(builds.ecr, "ensure_repository", fake_ensure)
    monkeypatch.setattr(builds.s3_upload, "put_bytes", fake_put_bytes)
    monkeypatch.setattr(builds.codebuild, "start_build", fake_start)
    monkeypatch.setattr(builds.repo, "put", fake_repo_put)
    # 确保 settings 有 project/bucket (否则 submit 抛 400)
    from app.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "codebuild_project_name", "proj", raising=False)
    monkeypatch.setattr(s, "image_build_source_bucket", "bkt", raising=False)

    body = SubmitBuildBody(
        dockerfile="FROM ubuntu",
        target_tag="my-ns/my-img:1.0",  # 路径式镜像名 (namespace/repo-name)
        uses=["training"],
        compute_type="BUILD_GENERAL1_LARGE",
    )
    item = await builds.submit_build("ws-1", body, {"user_id": "tester"})
    assert item["status"] == "building"
    assert captured["codebuild_id"] == "proj:abc"
    # repo 名 = 用户输入原文 (平台不加前缀); tag 作标签
    assert captured["target_repo"] == "my-ns/my-img"
    assert captured["target_uri"].endswith("/my-ns/my-img:1.0")
