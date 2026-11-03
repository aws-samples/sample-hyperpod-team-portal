"""DynamoDB 8 张表 + GSI (对齐 services/platform-api/app/adapters/ddb/tables.py).

表名 = {prefix}-{name}; 单数据源.
"""

from aws_cdk import CustomResource, Duration, RemovalPolicy
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import custom_resources as cr
from constructs import Construct

ATTR = ddb.AttributeType.STRING

# bootstrap 超管的 Lambda handler (内联): 运行时用 datetime.now() 生成 granted_at,
# 对传入的 username 列表逐个 PutItem 到 PlatformAdmins 表。幂等 (已存在则覆盖)。
_BOOTSTRAP_ADMIN_CODE = '''
import json, datetime, urllib.request
import boto3

ddb = boto3.client("dynamodb")

def _send(event, context, status, reason=""):
    body = json.dumps({
        "Status": status, "Reason": reason or "see CloudWatch",
        "PhysicalResourceId": event.get("PhysicalResourceId") or context.log_stream_name,
        "StackId": event["StackId"], "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"], "Data": {},
    }).encode()
    req = urllib.request.Request(event["ResponseURL"], data=body, method="PUT",
                                 headers={"content-type": "", "content-length": str(len(body))})
    urllib.request.urlopen(req)

def handler(event, context):
    try:
        if event["RequestType"] != "Delete":   # Create/Update 才写; Delete 不删超管 (表 RETAIN)
            props = event["ResourceProperties"]
            table = props["TableName"]
            admins = props["Admins"]            # list[str]
            now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            for u in admins:
                u = (u or "").strip()
                if not u:
                    continue
                ddb.put_item(TableName=table, Item={
                    "username":   {"S": u},
                    "granted_at": {"S": now},
                    "granted_by": {"S": "cdk-bootstrap"},
                    "notes":      {"S": "initial platform admin (cdk deploy)"},
                })
        _send(event, context, "SUCCESS")
    except Exception as e:
        _send(event, context, "FAILED", str(e))
'''


class DdbConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        prefix: str,
        bootstrap_admins: list[str] | None = None,
    ) -> None:
        super().__init__(scope, cid)
        self.prefix = prefix

        def table(name: str, pk: str, sk: str | None = None) -> ddb.Table:
            return ddb.Table(
                self, name,
                table_name=f"{prefix}-{name}",
                partition_key=ddb.Attribute(name=pk, type=ATTR),
                sort_key=ddb.Attribute(name=sk, type=ATTR) if sk else None,
                billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
                removal_policy=RemovalPolicy.RETAIN,
            )

        admins = table("PlatformAdmins", "username")

        workspaces = table("Workspaces", "workspace_id")
        workspaces.add_global_secondary_index(
            index_name="compute_quota_id-index",
            partition_key=ddb.Attribute(name="compute_quota_id", type=ATTR),
        )

        members = table("WorkspaceMembers", "workspace_id", "username")
        members.add_global_secondary_index(
            index_name="username-index",
            partition_key=ddb.Attribute(name="username", type=ATTR),
        )

        ridx = table("ResourceIndex", "workspace_id", "resource_key")
        ridx.add_global_secondary_index(
            index_name="creator-index",
            partition_key=ddb.Attribute(name="creator_username", type=ATTR),
        )
        ridx.add_global_secondary_index(
            index_name="type-time-index",
            partition_key=ddb.Attribute(name="resource_type", type=ATTR),
            sort_key=ddb.Attribute(name="created_at", type=ATTR),
        )
        # 稀疏 GSI: 仅活跃任务写 active_ws 顶层属性, 替代任务总览全分区 FilterExpression 扫
        ridx.add_global_secondary_index(
            index_name="active-index",
            partition_key=ddb.Attribute(name="active_ws", type=ATTR),
            sort_key=ddb.Attribute(name="created_at", type=ATTR),
        )
        # 按业务 id 精确取单行 GSI: PK=resource_id (全表唯一, 无需 SK)。
        # 替代 _find_by_id 的 list_by_type 全类型分区扫 + 内存轮询 (O(n)→O(1))。
        # by-id 路由是扁平 /{id}, 请求无 workspace_id (主表 PK), 故只能靠此 GSI
        # 精确定位。Projection=ALL: _find_by_id 要整行喂 _ri_to_* 反序列化。
        ridx.add_global_secondary_index(
            index_name="resource_id-index",
            partition_key=ddb.Attribute(name="resource_id", type=ATTR),
        )

        audit = table("AuditLog", "scope_key", "event_key")
        audit.add_global_secondary_index(
            index_name="actor-index",
            partition_key=ddb.Attribute(name="actor_username", type=ATTR),
        )

        # 成员级 FSx 挂载授权 (MountPermissions): PK=workspace_id,
        # SK=MOUNT#<mount_id>#USER#<username>; GSI username-index 查"我的权限".
        mount_perms = table("MountPermissions", "workspace_id", "perm_key")
        mount_perms.add_global_secondary_index(
            index_name="username-index",
            partition_key=ddb.Attribute(name="username", type=ATTR),
            sort_key=ddb.Attribute(name="workspace_id", type=ATTR),
        )

        # 资源模板 (开发机/训练/推理 公用一表): PK=workspace_id,
        # SK=<type>#default#<id> 或 <type>#custom#<user>#<id>。无 GSI。
        res_tpl = table("ResourceTemplates", "workspace_id", "sort_key")

        # 镜像中心 (工作空间镜像注册 · 引用模型): PK=workspace_id, SK="img#<id>"。
        # 任何 ws 成员可注册/删; 创建开发机/训练/推理时按 uses 筛选。无 GSI。
        ws_images = table("WorkspaceImages", "workspace_id", "sort_key")

        # 镜像在线构建任务/历史 (CodeBuild): PK=workspace_id, SK="build#<id>"。无 GSI。
        image_builds = table("ImageBuilds", "workspace_id", "sort_key")

        # 资源分享 (开发机/训练): PK=workspace_id, SK="SHARE#<type>#<id>#USER#<username>"。
        # GSI target-username-index 反查"分享给我的" (PK=target_username, SK=workspace_id)。
        shares = table("ResourceShares", "workspace_id", "share_key")
        shares.add_global_secondary_index(
            index_name="target-username-index",
            partition_key=ddb.Attribute(name="target_username", type=ATTR),
            sort_key=ddb.Attribute(name="workspace_id", type=ATTR),
        )

        # API Token (UI 申请个人 token): PK=username (每人一把);
        # 只存 token_hash (sha256), 验证按 hash 走 GSI token_hash-index 反查。
        api_tokens = table("ApiTokens", "username")
        api_tokens.add_global_secondary_index(
            index_name="token_hash-index",
            partition_key=ddb.Attribute(name="token_hash", type=ATTR),
        )

        self.tables = [
            admins, workspaces, members, ridx, audit, mount_perms, res_tpl,
            ws_images, image_builds, api_tokens, shares,
        ]
        # 后端 IAM policy 用: 所有表 + GSI 的 ARN
        self.table_arns = [t.table_arn for t in self.tables] + \
            [f"{t.table_arn}/index/*" for t in self.tables]

        # ---- bootstrap 超级管理员 (解决"鸡生蛋": 平台无 API 写 PlatformAdmins) ----
        # 部署时一个内联 Lambda 往 PlatformAdmins PutItem 写入初始超管, 字段对齐 repo.add()。
        # granted_at 在 Lambda 运行时用 datetime.now() 生成 (真实部署时刻, 非写死)。
        # username 必须 = IdC SAML 登录 token 的 identities[0].userId (非 cognito:username)。
        # PutItem 幂等 (已存在则覆盖); 列表空则不建任何 resource。
        admin_list = [u.strip() for u in (bootstrap_admins or []) if u.strip()]
        if admin_list:
            fn = lambda_.Function(
                self, "BootstrapAdminFn",
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler="index.handler",
                code=lambda_.Code.from_inline(_BOOTSTRAP_ADMIN_CODE),
                timeout=Duration.minutes(2),
            )
            admins.grant_write_data(fn)

            provider = cr.Provider(
                self, "BootstrapAdminProvider",
                on_event_handler=fn,
            )
            CustomResource(
                self, "BootstrapAdmins",
                service_token=provider.service_token,
                properties={
                    "TableName": admins.table_name,
                    "Admins": admin_list,
                    # Admins 变化时触发 Update 重新写 (granted_at 也会刷新成新部署时刻)
                },
            )
