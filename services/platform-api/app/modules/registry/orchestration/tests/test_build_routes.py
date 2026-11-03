"""镜像构建 4 个路由已注册。"""


def test_build_routes_registered():
    from app.modules.registry import registry_router

    paths = {r.path for r in registry_router.routes}
    assert "/workspaces/{ws_id}/image-builds" in paths
    assert "/workspaces/{ws_id}/image-builds/{build_id}" in paths
    assert "/workspaces/{ws_id}/image-builds/{build_id}/logs" in paths
