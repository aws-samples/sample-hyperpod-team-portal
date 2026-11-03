"""codebuild.start_build 参数组装测试 (mock aioboto3 client)。"""


async def test_start_build_returns_id(monkeypatch):
    from app.adapters.aws import codebuild

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def start_build(self, **kw):
            assert kw["projectName"] == "proj"
            assert kw["computeTypeOverride"] == "BUILD_GENERAL1_LARGE"
            env = {e["name"]: e["value"] for e in kw["environmentVariablesOverride"]}
            assert env["IMAGE_TAG"] == "t"
            return {"build": {"id": "proj:123"}}

    class FakeSession:
        def client(self, *a, **k):
            return FakeClient()

    monkeypatch.setattr(codebuild, "_session", lambda: FakeSession())
    bid = await codebuild.start_build(
        project="proj",
        source_zip_key="k.zip",
        compute_type="BUILD_GENERAL1_LARGE",
        ecr_uri="x/y",
        image_tag="t",
    )
    assert bid == "proj:123"
