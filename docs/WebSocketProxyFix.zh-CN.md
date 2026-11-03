# Code Editor WebSocket Proxy 修复日志

[English](WebSocketProxyFix.md) | **简体中文**

## 问题背景

通过 CloudFront + VPC Origin + Internal ALB 方案访问 HyperPod Code Editor (VS Code Web) 时，页面白屏，浏览器报 WebSocket 1006 错误。

**根因**：Code Editor 前端 JS 从 HTML `<meta>` 标签的 `remoteAuthority` 字段读取 WebSocket 连接目标，该字段值为 pod 内网 IP（如 `10.90.108.77:80`），浏览器无法通过公网连接 VPC 内网地址。

---

## 修复文件

`services/platform-api/app/modules/devinstance/api/router.py`

---

## 版本迭代

### v2 — HTML Rewrite（初版，有问题）

**改动**：在 `_proxy_jupyter_impl()` 返回 HTML 响应前，替换 `remoteAuthority`。

**问题**：替换时用了固定端口匹配（`pod_ip:8888`），但 HTML 中实际是 `pod_ip:80`，导致替换不生效。

```python
# v2 错误代码
pod_authority = f"{parsed.hostname}:{parsed.port or 8888}"
content = content.replace(pod_authority.encode(), external_authority.encode())

```

### v3 — 正则匹配任意端口 + 路径拼接（有问题）

**改动**：用正则 `pod_ip:\d+` 匹配任意端口。

**问题**：`external_authority` 包含了路径（`example.com/api/v1/dev-instances/{id}/proxy`），但 VS Code 的 `remoteAuthority` 只需要 host，路径由前端自动从页面 URL 继承。

```python
# v3 错误代码
external_authority = f"{external_host}/api/v1/dev-instances/{id}/proxy"
content = re.sub(pattern, external_authority.encode(), content)

```

### v4 — 正确的 HTML Rewrite（只替换为 host）✅

**改动**：`remoteAuthority` 只替换为域名（不含路径和端口）。

```python
# v4 正确代码
external_host = request.headers.get("host", request.url.hostname)
import re
pattern = re.escape(pod_ip).encode() + rb":\d+"
content = re.sub(pattern, external_host.encode(), content)

```

**效果**：

```
替换前: "remoteAuthority": "10.90.108.77:80"
替换后: "remoteAuthority": "example.com"

WebSocket URL: wss://example.com/api/v1/dev-instances/{id}/proxy/oss-unknown?...

```

### v4 — WebSocket Handler 认证增强

**改动**：WebSocket handler 原本只支持 Cognito JWT 认证，新增 API Token (`hypd_` 前缀) 支持。

```python
# 先尝试 API Token (hypd_ 前缀), 再尝试 Cognito JWT
try:
    if token.startswith("hypd_"):
        from app.core.auth_middleware import _verify_api_token
        await _verify_api_token(token)
    else:
        verify_cognito_id_token(token, settings)
except Exception as exc:
    # Cognito 验证失败时，也尝试 API Token 作为 fallback
    try:
        from app.core.auth_middleware import _verify_api_token
        await _verify_api_token(token)
    except Exception:
        logger.warning("dev_instance.proxy.ws_auth_fail", id=str(id), err=str(exc))
        await websocket.close(code=4401)
        return

```

### v5 — 缩进修复 ✅（已部署）

**改动**：修复 v4 中 `except Exception:` 块内的缩进错误（`logger.warning` 和 `websocket.close` 未正确包含在 except 内部）。已于 2026-06-13 22:06 CST 部署。

---

## 最终验证结果

| 检查项 | 状态 |
| --- | --- |
| `remoteAuthority` 替换为 `example.com` | ✅ |
| WebSocket 通过 CloudFront → VPC Origin → ALB 到达后端 | ✅ |
| WebSocket 认证支持 Cognito JWT | ✅ |
| WebSocket 认证支持 API Token (hypd_) | ✅ |
| Extension Host 连接成功 | ✅ (`successful after 702 ms`) |
| Code Editor 界面可加载 | ✅ |

---

## 关键发现

1. **CloudFront VPC Origin 从 2026-05-01 起支持 WebSocket**（[公告](https://aws.amazon.com/about-aws/whats-new/2026/05/amazon-cloudfront-websockets-vpc-origins/)）
2. VS Code Web 的 `remoteAuthority` 只需要 `host(:port)`，路径由前端从页面 URL 自动继承
3. WebSocket handler 的认证逻辑独立于 HTTP AuthMiddleware（middleware 不拦 websocket scope），需要在 handler 内自行验证
4. cookie `dev_proxy_token` 由 HTTP proxy 首次访问时种入，WebSocket 握手时浏览器自动携带

---

## 部署命令

```bash
# 当前线上: v5 ✅ (2026-06-13 22:06 CST 部署)
# v4 可用但有缩进 bug (edge case)
# v5 = v4 + 缩进修复 (稳定版)

```

