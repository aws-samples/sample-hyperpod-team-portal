# Code Editor WebSocket Proxy Fix Log

**English** | [简体中文](WebSocketProxyFix.zh-CN.md)

## Background

When accessing HyperPod Code Editor (VS Code Web) through the CloudFront + VPC Origin + Internal ALB setup, the page is blank and the browser reports WebSocket error 1006.

**Root cause**: The Code Editor frontend JS reads the WebSocket connection target from the `remoteAuthority` field of an HTML `<meta>` tag. That value is the pod's private IP (e.g. `10.90.108.77:80`), and the browser cannot reach a private VPC address over the internet.

---

## Fixed File

`services/platform-api/app/modules/devinstance/api/router.py`

---

## Iterations

### v2 — HTML Rewrite (first version, broken)

**Change**: Replace `remoteAuthority` in `_proxy_jupyter_impl()` before returning the HTML response.

**Problem**: The replacement matched a fixed port (`pod_ip:8888`), but the HTML actually contains `pod_ip:80`, so the replacement had no effect.

```python
# v2 buggy code
pod_authority = f"{parsed.hostname}:{parsed.port or 8888}"
content = content.replace(pod_authority.encode(), external_authority.encode())

```

### v3 — Regex Matching Any Port + Path Concatenation (broken)

**Change**: Use the regex `pod_ip:\d+` to match any port.

**Problem**: `external_authority` included a path (`example.com/api/v1/dev-instances/{id}/proxy`), but VS Code's `remoteAuthority` only needs the host; the frontend inherits the path from the page URL automatically.

```python
# v3 buggy code
external_authority = f"{external_host}/api/v1/dev-instances/{id}/proxy"
content = re.sub(pattern, external_authority.encode(), content)

```

### v4 — Correct HTML Rewrite (Host Only) ✅

**Change**: Replace `remoteAuthority` with the domain only (no path, no port).

```python
# v4 correct code
external_host = request.headers.get("host", request.url.hostname)
import re
pattern = re.escape(pod_ip).encode() + rb":\d+"
content = re.sub(pattern, external_host.encode(), content)

```

**Result**:

```
Before: "remoteAuthority": "10.90.108.77:80"
After: "remoteAuthority": "example.com"

WebSocket URL: wss://example.com/api/v1/dev-instances/{id}/proxy/oss-unknown?...

```

### v4 — WebSocket Handler Authentication Enhancement

**Change**: The WebSocket handler originally supported only Cognito JWT authentication; support for API tokens (`hypd_` prefix) was added.

```python
# Try API Token (hypd_ prefix) first, then Cognito JWT
try:
    if token.startswith("hypd_"):
        from app.core.auth_middleware import _verify_api_token
        await _verify_api_token(token)
    else:
        verify_cognito_id_token(token, settings)
except Exception as exc:
    # If Cognito verification fails, also try API Token as a fallback
    try:
        from app.core.auth_middleware import _verify_api_token
        await _verify_api_token(token)
    except Exception:
        logger.warning("dev_instance.proxy.ws_auth_fail", id=str(id), err=str(exc))
        await websocket.close(code=4401)
        return

```

### v5 — Indentation Fix ✅ (Deployed)

**Change**: Fixed an indentation error in v4's `except Exception:` block (`logger.warning` and `websocket.close` were not correctly nested inside the except). Deployed at 2026-06-13 22:06 CST.

---

## Final Verification Results

| Check | Status |
| --- | --- |
| `remoteAuthority` replaced with `example.com` | ✅ |
| WebSocket reaches the backend via CloudFront → VPC Origin → ALB | ✅ |
| WebSocket authentication supports Cognito JWT | ✅ |
| WebSocket authentication supports API token (hypd_) | ✅ |
| Extension Host connects successfully | ✅ (`successful after 702 ms`) |
| Code Editor UI loads | ✅ |

---

## Key Findings

1. **CloudFront VPC Origin supports WebSocket as of 2026-05-01** ([announcement](https://aws.amazon.com/about-aws/whats-new/2026/05/amazon-cloudfront-websockets-vpc-origins/))
2. VS Code Web's `remoteAuthority` only needs `host(:port)`; the frontend inherits the path from the page URL automatically
3. The WebSocket handler's authentication logic is independent of the HTTP AuthMiddleware (the middleware does not intercept the websocket scope), so the handler must verify credentials itself
4. The `dev_proxy_token` cookie is set by the HTTP proxy on first access, and the browser sends it automatically during the WebSocket handshake

---

## Deployment Commands

```bash
# Currently live: v5 ✅ (deployed 2026-06-13 22:06 CST)
# v4 works but has an indentation bug (edge case)
# v5 = v4 + indentation fix (stable version)

```

