"""v1 API 汇总路由"""

from fastapi import APIRouter, Depends

from app.core.security import require_admin
from app.modules.admin.router import admin_router
from app.modules.auth.api.router import auth_router
from app.modules.cluster.api.router import cluster_router
from app.modules.devinstance.api.router import router as dev_instance_router
from app.modules.dynamo import dynamo_router
from app.modules.fsx_quota.api.router import fsx_quota_router
from app.modules.fsx_quota.api.monitoring_router import fsx_monitoring_router
from app.modules.inference import inference_router
from app.modules.llmd import llmd_router
from app.modules.logs.router import logs_router
from app.modules.monitoring.router import monitoring_router
from app.modules.priority import priority_router
from app.modules.quota.api.router import quota_router
from app.modules.rayjob import rayjob_router
from app.modules.registry import registry_router
from app.modules.resource_templates import resource_templates_router
from app.modules.secret import secret_router
from app.modules.sharing.api.router import router as sharing_router
from app.modules.tasks import tasks_router
from app.modules.training import training_router
from app.modules.user.api.router import idc_router
from app.modules.user.router import user_router
from app.modules.workspace.api.fsx_router import fsx_router, ws_fsx_router
from app.modules.workspace.api.router import workspace_router
from app.modules.workspace.api.s3_router import s3_bucket_router, ws_s3_router

# 把 ws 内 fsx + s3 路由合并到 workspace_router (共享 /workspaces 前缀)
workspace_router.include_router(ws_fsx_router)
workspace_router.include_router(ws_s3_router)

api_v1_router = APIRouter()
# auth_router 端点自带 /auth/config (前端 PKCE flow 取公开 OIDC 配置, 无需认证)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(
    admin_router, prefix="/admin", dependencies=[Depends(require_admin)]
)
# fsx_quota_router 端点自带 /admin/fsx-quota/* (目录配额, 平台超管)
api_v1_router.include_router(fsx_quota_router)
# fsx_monitoring_router 端点自带 /monitoring/fsx/* (CloudWatch 指标, 所有登录用户可看)
api_v1_router.include_router(fsx_monitoring_router)
api_v1_router.include_router(cluster_router, prefix="/clusters")
api_v1_router.include_router(user_router, prefix="/users")
# idc_router: GET /api/v1/idc/users?q=... (admin 加成员搜索 IdC)
api_v1_router.include_router(idc_router)
api_v1_router.include_router(workspace_router, prefix="/workspaces")
# quota_router 端点自带完整路径
#   - /workspaces/{id}/quota[*]      (ComputeQuota CRUD)
#   - /workspaces/{id}/quota/usage   (live Kueue usage · B4 合并 quota_usage 后统一)
#   - /clusters/{tag}/quotas         (cluster 维度列表)
api_v1_router.include_router(quota_router)
# fsx_router: GET /api/v1/fsx-filesystems (列候选池)
api_v1_router.include_router(fsx_router)
# s3_bucket_router: GET /api/v1/s3-buckets (列候选池)
api_v1_router.include_router(s3_bucket_router)
# dev_instance_router 端点自带 /workspaces/{id}/dev-instances + /dev-instances/...
api_v1_router.include_router(dev_instance_router)
# training_router 端点自带 /workspaces/{id}/training-jobs + /training-jobs/...
api_v1_router.include_router(training_router)
# inference_router 端点自带 /workspaces/{id}/inferences + /inferences/{id}
api_v1_router.include_router(inference_router)
# dynamo_router 端点自带 /workspaces/{id}/dynamo-inferences + /dynamo-inferences/{id} (多机推理)
api_v1_router.include_router(dynamo_router)
# rayjob_router 端点自带 /workspaces/{id}/rayjobs + /rayjobs/{id} (Ray 训练, 与训练平级)
api_v1_router.include_router(rayjob_router)
# llmd_router 端点自带 /workspaces/{id}/llmd + /llmd/{id} (LWS+sgl-gateway 多机推理, 与 dynamo 平级)
api_v1_router.include_router(llmd_router)
# resource_templates_router 端点自带 /workspaces/{id}/resource-templates
api_v1_router.include_router(resource_templates_router)
# tasks_router 端点自带 /workspaces/{id}/tasks (任务总览, 全 workspace 只读)
api_v1_router.include_router(tasks_router)
# priority_router: /priority-classes + /workspaces/{id}/workloads|preemption|tasks/.../priority
api_v1_router.include_router(priority_router)
# monitoring_router 端点自带 /monitoring/* + /training-jobs/{id}/monitoring/... +
#                            /dev-instances/{id}/monitoring/...
api_v1_router.include_router(monitoring_router)
# logs_router 端点自带 /training-jobs/{id}/logs (CW Logs Insights)
api_v1_router.include_router(logs_router)
# registry_router 端点自带 /registry/ecr/* + /registry/s3/* (训练表单 dropdown)
api_v1_router.include_router(registry_router)
# secret_router 端点自带 /workspaces/{id}/secrets (每人管自己的通用 key-value Secret)
api_v1_router.include_router(secret_router)
# sharing_router 端点自带 /workspaces/{id}/shares[/...] (开发机/训练分享给同 ws 成员)
api_v1_router.include_router(sharing_router)
