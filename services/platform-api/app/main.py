"""Platform API FastAPI entrypoint (DDB-only).

启动流程:
1. setup_logging (structlog)
2. lifespan: ddb.ping() 验证 5 张 DDB 表可达 (失败也只 warn, 不 abort —
   Pod 启动期允许 IAM 还没就位)
3. 挂 /api/v1 + /healthz + /api/scalar (API Reference)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from scalar_fastapi import Layout, Theme, get_scalar_api_reference

from app.adapters.ddb.client import ping as ddb_ping
from app.api.v1.router import api_v1_router
from app.core.auth_middleware import AuthMiddleware
from app.core.i18n import validate_catalogs
from app.core.locale_middleware import LocaleMiddleware
from app.core.logging import get_logger, setup_logging


def _unique_operation_id(route: APIRoute) -> str:
    method = next(iter(route.methods or ["get"])).lower()
    fn_name = route.endpoint.__name__
    return f"{fn_name}_{method}"


setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 文案表缺失 = 镜像打包错误, 必须启动即失败 (允许抛); DDB 则可能只是 IAM 暂未就位, 仅 warn。
    validate_catalogs()
    logger.info("platform_api.startup.i18n_ok")

    try:
        ok = await ddb_ping()
        if ok:
            logger.info("platform_api.startup.ddb_ok")
        else:
            logger.warning("platform_api.startup.ddb_partial",
                           hint="some tables missing; run scripts/ddb-local-bootstrap.py or check IAM")
    except Exception as exc:  # noqa: BLE001
        logger.warning("platform_api.startup.ddb_unreachable", error=str(exc))

    # 平台已切 directSSH: 连接靠 addon 的固定 DNS + sshd:22222, 不再有 SSM
    # 边车注册, 原 ssm_recovery_sweep 自愈任务随之停用 (无 mi 可恢复)。
    yield

    logger.info("platform_api.shutdown")


_API_DESCRIPTION = """\
HyperPod Platform API — 把 SageMaker HyperPod + EKS + Kueue 包装成 GPU 算力平台的后端.

前端 / CLI / 脚本按下面这些资源类别按 REST 语义调用. 大多数路径都遵循
`/api/v1/workspaces/{ws_id}/<resource>` (工作空间作用域, 需 ws 成员或超管)
或 `/api/v1/<resource>/{id}` (跨 ws 查单条, 权限按资源所属 ws 判定).

**认证**: 除 `/auth/config` 和文档路径外, 全部走 `Authorization: Bearer <JWT>`
(Cognito 出的 OIDC token, 或个人 API Token — 见 `/workspaces/{id}/secrets`).

**幂等性**: POST 创建接口默认非幂等 (同名会 409). PATCH / DELETE 幂等 (删已删返 204).

**架构**: DDB 单源 — 平台状态全落 DynamoDB, K8s CR 由 controller 派生;
详情读默认纯读 DDB, `?sync=true` 才实时拉 K8s.
"""

# openapi_tags: 侧边栏分组 + 每组顶栏中文说明.
# tag 顺序 = 侧边栏顺序, 按"用户日常路径"从上到下排 (工作空间 → 三类任务 → 平台设施).
# x-displayName: Scalar 侧边栏展示名 (中文, 专有名词保留英文); name 是 tag 内部标识,
# 不影响接口路径, 不要改.
_OPENAPI_TAGS = [
    {"name": "auth", "x-displayName": "认证", "description": "OIDC 公开配置 (SPA PKCE flow 启动用, 无鉴权)."},
    {"name": "users", "x-displayName": "用户", "description": "当前登录用户 profile / 偏好."},
    {"name": "idc", "x-displayName": "IAM 用户搜索", "description": "IAM Identity Center 用户搜索 (admin 加成员用)."},
    {
        "name": "workspaces",
        "x-displayName": "工作空间",
        "description": "工作空间 = K8s namespace + Kueue queue + FSx + 配额. 团队隔离单元.",
    },
    {
        "name": "quota",
        "x-displayName": "配额",
        "description": "ComputeQuota (SageMaker) + Kueue 实时用量. 建/改/删 quota 会同步到 K8s namespace/ClusterQueue.",
    },
    {
        "name": "quota-usage",
        "x-displayName": "配额用量",
        "description": "Kueue 实时用量 (ws 视角) — 每种 flavor 的 nominalQuota / used / borrowed.",
    },
    {
        "name": "fsx",
        "x-displayName": "FSx 文件系统",
        "description": "FSx for Lustre 文件系统候选池 (跨 ws 只读列表, 供 ws 配置时选).",
    },
    {"name": "s3-buckets", "x-displayName": "S3 候选池", "description": "S3 桶候选池 (跨 ws 只读列表, 供 ws 配置时选)."},
    {"name": "s3", "x-displayName": "S3 挂载", "description": "工作空间 S3 挂载 (Mountpoint S3 CSI Driver, 全局只读)."},
    {
        "name": "dev-instances",
        "x-displayName": "开发机",
        "description": "云端 Jupyter / VS Code 开发机 (Sagemaker Spaces). 含创建 / 状态 / SSM proxy / 端口转发.",
    },
    {
        "name": "training-jobs",
        "x-displayName": "训练任务",
        "description": "分布式 PyTorch 训练 (HyperPodPyTorchJob + hyperpodrun). Kueue 排队, 支持挂 FSx/S3.",
    },
    {
        "name": "rayjob",
        "x-displayName": "Ray 训练",
        "description": "Ray 分布式训练 (KubeRay RayJob). Kueue 排队, 支持挂 FSx/S3.",
    },
    {
        "name": "inferences",
        "x-displayName": "推理服务",
        "description": "推理服务 (SGLang 引擎, InferenceEndpointConfig CR). 三种调用方式: 集群内 / VPC ALB / SageMaker Endpoint.",
    },
    {
        "name": "llmd",
        "x-displayName": "llm-d 推理",
        "description": "llm-d 多机推理 (LeaderWorkerSet + sgl-gateway). 统一网关 + 多组推理副本.",
    },
    {
        "name": "resource-templates",
        "x-displayName": "资源模板",
        "description": "资源模板 (ws 级) — 机型 + GPU/CPU/内存 打包. 三类任务共用, 只能选不能填.",
    },
    {"name": "tasks", "x-displayName": "任务总览", "description": "任务总览 (跨三类任务只读列表, 供全 ws 视图)."},
    {
        "name": "priority",
        "x-displayName": "优先级",
        "description": "Kueue 优先级档位 · workspace 抢占开关 · 任务优先级调整.",
    },
    {
        "name": "monitoring",
        "x-displayName": "监控",
        "description": (
            "监控指标: GPU / Pod (DCGM + cAdvisor, AMP 拉取, 按 pod 过滤) · "
            "FSx CloudWatch 指标 (util / free / tput / iops, 全局视图, 所有登录用户可看)."
        ),
    },
    {"name": "logs", "x-displayName": "日志", "description": "CloudWatch Logs Insights — 实时 / 历史日志, 支持跨 pod 全任务搜索."},
    {"name": "registry", "x-displayName": "镜像中心", "description": "ECR / S3 镜像 · 代码物料候选池 (创建表单 dropdown 用)."},
    {"name": "secret", "x-displayName": "Token 中心", "description": "个人 API Token / Secret (每人管自己的)."},
    {"name": "sharing", "x-displayName": "资源分享", "description": "把开发机 / 训练任务分享给同 ws 成员 (共享读权)."},
    {"name": "clusters", "x-displayName": "集群", "description": "HyperPod 集群元信息 (只读). 前端切集群时用."},
    {
        "name": "admin",
        "x-displayName": "管理中心",
        "description": (
            "超管专用: 全局配置 · 全 ws 审计 · FSx 一级目录 project quota 管理 "
            "(建目录 / 改配额 / 列用量)."
        ),
    },
    {"name": "meta", "x-displayName": "健康检查", "description": "健康检查 / 探针."},
]

app = FastAPI(
    title="HyperPod Platform API",
    version="0.1.0",
    description=_API_DESCRIPTION,
    license_info={"name": "MIT-0", "identifier": "MIT-0"},
    openapi_tags=_OPENAPI_TAGS,
    lifespan=lifespan,
    generate_unique_id_function=_unique_operation_id,
    # 文档统一挂到 /api 前缀下 (方案B): 走已有的 "/api → 后端" ingress 规则
    # (dev 的 vite proxy 同理), dev/prod 都无需额外代理 / ingress 路由.
    # 注意: /docs 留给前端「产品文档」SPA 路由, 故 Swagger 用 /api/docs 避免冲突.
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect",
)

# ⚠️ Middleware 注册顺序: 后注册的先执行 (LIFO).
# 我们要的执行顺序: CORS (handle preflight) → Locale (定请求语言) → Auth (验签) → app.
# 所以代码里先 add Auth, 再 add Locale, 最后 add CORS, 让 CORS 在请求链最外层;
# Locale 在 Auth 之外, 后续所有层 (含 Auth 与业务报错) 都能读到请求语言.
app.add_middleware(AuthMiddleware)
app.add_middleware(LocaleMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router, prefix="/api/v1")


@app.get("/api/scalar", include_in_schema=False)
async def scalar_html() -> HTMLResponse:
    """Scalar API Reference · 消费 FastAPI 自带的 /api/openapi.json.

    与 /api/docs (Swagger) / /api/redoc 并存, 三者同一份 OpenAPI 文档.
    全部挂在 /api 前缀下, 走已有的 "/api → 后端" 路由 (dev/prod 一致).
    注意: Scalar 前端 JS 默认从 CDN (cdn.jsdelivr.net) 加载 —
    访问者浏览器需能连 CDN. 内网/隔离环境可改 scalar_js_url 指向自托管 bundle.
    路径已在 AuthMiddleware 白名单 (_WHITELIST_PREFIXES) 放行.
    """
    return get_scalar_api_reference(
        openapi_url=app.openapi_url or "/api/openapi.json",
        title=f"{app.title} · API Reference",
        # ------- 版面 -------
        layout=Layout.MODERN,
        theme=Theme.DEFAULT,
        # 支持深色模式并保留用户切换 (默认跟随系统)
        hide_dark_mode_toggle=False,
        # ------- 侧边栏 / 分组 -------
        show_sidebar=True,
        # 默认展开所有 tag 分组 — 让"工作空间 / 推理 / 训练" 一次看全
        default_open_all_tags=True,
        # ------- 交互 -------
        # 允许在页面里直接发测试请求 (走当前浏览器凭证, 走同源 /api)
        hide_test_request_button=False,
        # 记住输入过的 Bearer token / API key, 页面刷新不用重填
        persist_auth=True,
        # 显示当前 servers 下拉 (读 OpenAPI servers) — 让前端 dev 快速切 dev/prod
        # servers 列表由 FastAPI 从 request 推导; 手动可以在 app.servers 加
        # ------- 显式 servers (方便非同源调用: 如 postman / curl 复制 base URL) -------
        servers=[
            {"url": "/", "description": "当前站点 (推荐, 走 /api 前缀同源)"},
        ],
        # ------- schema 展示 -------
        # 默认不展开所有 model — 太多; 但把 required 属性排到前面
        expand_all_model_sections=False,
        order_required_properties_first=True,
        order_schema_properties_by="preserve",
        # 保留下载按钮 (json + yaml 都给) 让人可以本地保存 spec
        # ------- 品牌 / 视觉 -------
        # 用 FastAPI 自带 favicon 太通用了; 保留默认或换成平台 logo
        # 关掉 telemetry (Scalar 默认会往 scalar.com 报是否发过测试请求)
        telemetry=False,
    )


@app.get("/healthz", tags=["meta"])
async def healthz() -> dict[str, str]:
    try:
        ok = await ddb_ping()
    except Exception as exc:  # noqa: BLE001
        logger.error("platform_api.healthz.ddb_fail", error=str(exc))
        return {"status": "degraded", "ddb": "fail"}
    return {"status": "ok" if ok else "degraded", "ddb": "ok" if ok else "missing-tables"}
