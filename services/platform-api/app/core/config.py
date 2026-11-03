from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Platform API 配置 - 从 .env.local 读取（本地）或容器环境变量（生产）"""

    model_config = SettingsConfigDict(
        env_file=[".env.local", ".env"],
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ===== 应用 =====
    app_env: str = Field(default="local", description="local/dev/staging/prod")
    log_level: str = Field(default="DEBUG")
    log_format: str = Field(default="console", description="console/json")

    # ===== AWS =====
    aws_region: str = Field(default="us-west-2")
    aws_profile: str | None = Field(default=None, description="本地调试用;生产留空走 IRSA/实例 Role")

    # ===== DynamoDB (单数据源, 替代 RDS+Redis) =====
    ddb_table_prefix: str = Field(default="hypd-local", description="表前缀: hypd-local/hypd-dev/hypd-prod")
    ddb_endpoint_url: str | None = Field(
        default="http://localhost:8000",
        description="本地 DynamoDB Local 用; 生产留空走 AWS 真实 endpoint",
    )

    # ===== Kubernetes =====
    kubeconfig_path: str = Field(default="~/.kube/config")
    kube_context: str = Field(default="")
    # 跨集群部署: 平台前后端跑在独立平台集群, 业务资源(开发机)在另一个业务集群.
    # True 时开发机 HTTP 代理跳过 .svc.cluster.local DNS (平台集群解析不到业务集群
    # service), 直接走 podIP (需两集群 podIP 互通 / 同 VPC). 单集群部署留 False.
    cross_cluster_mode: bool = Field(default=False)

    # ===== FSx admin pod (list 子目录用; deploy/k8s/fsx-admin.yaml) =====
    fsx_admin_namespace: str = Field(default="hyperpod-platform-system")
    fsx_admin_label_selector: str = Field(default="app=fsx-admin")
    fsx_admin_container: str = Field(default="sh")

    # ---- 默认优先级档 (按任务类型) ----
    # 优先级档权威源已迁到 HyperPod task governance; 这里只配"每类任务提交时默认打哪个档 name".
    # 映射查不到 → priority_default_fallback. 不做 WPC 存在性校验 (缺失时 Kueue priority=0).
    priority_default_fallback: str = Field(default="common-priority")
    priority_default_train: str = Field(default="common-priority")
    priority_default_inference: str = Field(default="common-priority")
    priority_default_dynamo: str = Field(default="common-priority")
    priority_default_llmd: str = Field(default="common-priority")
    priority_default_rayjob: str = Field(default="common-priority")
    priority_default_devinstance: str = Field(default="common-priority")

    # ===== 认证 =====
    cognito_user_pool_id: str = Field(default="")
    cognito_client_id: str = Field(default="")
    cognito_region: str = Field(default="us-west-2")
    # Cognito Hosted UI 域名 (前端 PKCE flow 跳转用) · 不带 https://
    # 例: ap-south-1prvxfghiw.auth.ap-south-1.amazoncognito.com
    cognito_domain: str = Field(default="")
    # 本地 PKCE callback URL · Cognito App Client Allowed callback URLs 必须含此值
    # 生产环境前端跑 ALB 后面, 这个值给本地 dev 用
    local_callback_url: str = Field(
        default="http://localhost:5173/auth/callback",
        description="本地 PKCE flow callback (生产可忽略)",
    )
    # 部署 ALB authenticate-cognito 后, ALB 自己签的 JWT 注入 x-amzn-oidc-data,
    # 后端验签时要用这个 ARN 校验 signer claim, 防别的 ALB 的 token 被拿来用.
    # 本地不部署 ALB, 留空即可 (middleware 自动 fallback 走 Bearer 路径)
    alb_arn: str = Field(
        default="",
        description="ALB ARN (生产 Fargate 部署填; 本地留空)",
    )

    # ===== HyperPod / EKS =====
    hyperpod_cluster_name: str = Field(default="")
    log_group_name: str = Field(
        default="",
        description=(
            "预拼好的完整 CloudWatch log group 名 "
            "(/aws/sagemaker/Clusters/{tag}/{cluster-id-suffix})。"
            "设置后日志 resolver 直接用它, 跳过 ws_get + SageMaker DescribeCluster "
            "(单集群部署优化); 留空则回退按 ws->cluster 动态推导 (多集群)。"
        ),
    )
    eks_cluster_name: str = Field(
        default="",
        description="EKS 集群名 (eks:CreatePodIdentityAssociation 用) · 与 hyperpod_cluster_name 不同概念",
    )

    # ===== 镜像中心在线构建 (CodeBuild) =====
    codebuild_project_name: str = Field(
        default="", description="镜像构建 CodeBuild project 名; 空则构建功能禁用"
    )
    image_build_source_bucket: str = Field(
        default="", description="镜像构建 context (Dockerfile+buildspec zip) 的 S3 桶"
    )

    # ===== FSx (多文件系统) =====
    # 平台可接入多块 FSx for Lustre. 逗号分隔 fs-id 列表。fs-id 直接当 fsx-admin
    # pod 挂载点子目录 /fsx-mnt/<fs-id> (天然路径安全); 前端下拉展示名走 AWS
    # Tags[Name]。兼容旧格式 fs-id:别名 (取冒号前 fs-id, 忽略别名段)。
    # 例: PLATFORM_FSX_FILESYSTEMS=fs-0c0b...,fs-0ffa...
    # 留空时候选池 fallback 到 Tags[managed]=hyperpod 过滤 (仅展示, 不可做配额)。
    platform_fsx_filesystems: str = Field(
        default="",
        description="FSx 列表 · fs-id 逗号分隔",
    )

    # ===== S3 候选池 =====
    # 替代 list_buckets + get_bucket_tagging 的 N+1 慢链 (账号 100 个 bucket 时
    # 串行调用 100 次 get_bucket_tagging 要 ~26s). 设置此变量后直接读, 不查 AWS.
    # 格式: bucket1[:region1[:friendly_name1]],bucket2[:region2[:friendly_name2]]
    #     - region 可选 · 不填走 settings.aws_region
    #     - friendly_name 可选 · 不填用 bucket name 当展示名
    # 例:
    #   PLATFORM_S3_BUCKETS=hyperpod-test-dataset-ap-south-1:ap-south-1:训练数据集,team-b-data
    # 留空时 fallback 到 list_buckets + tag 过滤的老路径.
    platform_s3_buckets: str = Field(
        default="",
        description="S3 候选池 · 直接列出 bucket (跳过 tag 扫描)",
    )

    # ===== Workspace pod 共用 IAM role =====
    # ws 创建时建 ServiceAccount workspace-default, 通过 EKS Pod Identity 关联到这个 role.
    # 集群里所有 ws 的 pod (开发机/训练/推理) 共用一份, 隔离靠 K8s PVC + claimRef + RBAC.
    platform_pod_role_arn: str = Field(default="")

    # ===== IAM Identity Center (IdC) =====
    # admin 加 ws 成员时要拿真 email/display_name, 走 identitystore:GetUserId +
    # DescribeUser 实时查 (M1 走精确等值搜索, 200-5000 人都不卡).
    # IdentityStoreId 在 IAM Identity Center → Settings 看, 形如 d-xxxxxxxx.
    idc_identity_store_id: str = Field(default="")
    # IdC 实例的 home region. 可能 ≠ 平台主区域 aws_region (IdC 实例只在它自己
    # 那个 region 可达). 留空回落到 aws_region. 例: 平台跑 us-west-2 但 IdC 在
    # ap-south-1 时, 必须设 IDC_REGION=ap-south-1, 否则 identitystore 调用报
    # ResourceNotFoundException (store 在 us-west-2 不存在).
    idc_region: str = Field(default="")
    # 跨账号: IdC 在 org 管理账号(或委派管理员账号), 应用部署在另一个账号时,
    # 应用本地凭证看不到对方账号的 Identity Store. 配上对方账号一个只读角色 ARN
    # (信任本应用 pod role, 权限仅 identitystore:GetUserId + DescribeUser), 后端
    # 先 sts:AssumeRole 拿临时凭证再建 identitystore client. 留空 = 同账号, 直接
    # 用本地凭证 (IRSA/Pod Identity/实例 Role/profile). 注意: assume 后建 client 仍
    # 需 IDC_REGION + IDC_IDENTITY_STORE_ID 指向管理账号那个 store.
    # 形如 arn:aws:iam::<mgmt-account-id>:role/hyperpod-idc-readonly.
    idc_assume_role_arn: str = Field(default="")

    # ===== SSM Activation (sidecar 注册) =====
    # 后端绕过 spaces 0.1.5 sidecar 死锁的关键: 主动调 ssm:CreateActivation +
    # kubectl exec sidecar -- register-ssm.sh 注入 (ACTIVATION_ID, CODE, REGION).
    # 这个 ARN 是 sidecar 注册成 SSM managed instance 时绑定的 IAM role
    # (它需要 trust ssm.amazonaws.com + sagemaker.amazonaws.com 双 principal).
    ssm_managed_node_role_arn: str = Field(
        default="",
        description="SSM Activation 用的 IAM role ARN (sagemaker-space-SSMManagedNode-*)",
    )

    # ===== 开发机 HTTP 代理 (浏览器开 JupyterLab/Code Editor) =====
    # 三层目标解析顺序 (router.py:_resolve_proxy_target):
    #   1) 设了 dev_proxy_local_target → 走该地址 (本地 mac 用 kubectl
    #      port-forward 转发到 localhost:18888 调试)
    #   2) 容器内 KUBERNETES_SERVICE_HOST 在 → service DNS (生产 in-cluster)
    #   3) podIP fallback (后端在 VPC 外但路由打通时)
    # 生产 EKS 部署一般不用配, 自动走第 2 条.
    dev_proxy_local_target: str = Field(
        default="",
        description="本地 hack: localhost:18888 (kubectl port-forward 端口); 生产留空",
    )
    # 浏览器 window.open(/proxy/) 是导航请求, 无法设 Authorization header.
    # 启用此项后, auth_middleware 会放行 /proxy/* 路径下 ?access_token= query
    # 参数. 仅本地 mac 调试用; 生产 ALB authenticate-cognito 自带 session
    # cookie, 不需要 query token, 此项保持 False.
    enable_dev_proxy_query_token: bool = Field(
        default=False,
        description="放行 /proxy/?access_token= query 参数 (M1 本地 hack, 生产禁用)",
    )

    # ===== Monitoring (AMP — Amazon Managed Prometheus) =====
    # 监控取数统一走 AMP + SigV4 (本地 / 生产同源). 必须配 AMP_WORKSPACE_ID,
    # 否则 /monitoring 取数报错. 凭证: 本地 aws cli profile, 生产 Pod Identity.
    #   endpoint: https://aps-workspaces.<region>.amazonaws.com/workspaces/<ws_id>
    amp_workspace_id: str | None = Field(default=None)

    # ===== Cache TTL（秒）=====
    cache_ttl_cluster_summary: int = Field(default=30)
    cache_ttl_nodes: int = Field(default=30)
    cache_ttl_quotas: int = Field(default=60)

    @property
    def is_local(self) -> bool:
        return self.app_env == "local"

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def kubeconfig_abs_path(self) -> str:
        return str(Path(self.kubeconfig_path).expanduser().resolve())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
