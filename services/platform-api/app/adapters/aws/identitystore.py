"""AWS IAM Identity Center (IdC, 旧称 SSO) adapter.

职责:
    - find_user(q): admin 加成员时实时查用户. q 是完整 username 或 完整 email
                    (含 @ 视作 email, 否则视作 username).
                    走 identitystore:GetUserId + DescribeUser, 不分页, ~100-200ms.
                    找不到返 None.
    - describe_user_by_id: 已知 UserId 拿全部信息 (后续接管理员任命场景用).

为什么不用 ListUsers:
    AWS Filters 已 deprecated, 只支持 1 个 filter, 仅 UserName 精确匹配.
    全量分页 5000 人需要 25-50s + 5min cache 增加复杂度.
    精确等值是 IdC 实际能用的搜索方式 (见调研报告 2026-05-26).

需要 IAM:
    identitystore:GetUserId
    identitystore:DescribeUser
    Resource: "*"  (IdC 不支持资源级 ARN)

跨账号 (IdC 在 org 管理账号, 应用在另一个账号):
    设 IDC_ASSUME_ROLE_ARN = 管理账号一个只读角色 ARN (信任本 pod role,
    权限仅上面两个 identitystore action). 后端先 sts:AssumeRole 拿临时凭证,
    再用临时凭证建 identitystore client. 上面的 IAM 改挂在管理账号那个角色上,
    本应用 pod role 只需 sts:AssumeRole 到该 ARN. 留空 = 同账号, 走本地凭证.
"""

from __future__ import annotations

import time
from typing import Any

import aioboto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings
from app.core.i18n import t
from app.core.logging import get_logger

logger = get_logger(__name__)

# 跨账号临时凭证缓存: 避免每次查人都 sts:AssumeRole (多一跳 ~100ms + STS 限流).
# 1h 有效期, 到期前 5min 主动刷新. 单 worker 进程内存, 重启即弃, 无需持久化.
_ASSUME_TTL_SKEW_SECONDS = 300
_idc_creds_cache: dict[str, Any] | None = None
_idc_creds_expiry: float = 0.0


class IdcAPIError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


async def _assume_idc_creds(role_arn: str, region: str) -> dict[str, Any]:
    """sts:AssumeRole 到管理账号只读角色, 返回 boto3 client 用的凭证 kwargs.

    带进程内缓存 (按过期时间复用). 失败抛 IdcAPIError.
    """
    global _idc_creds_cache, _idc_creds_expiry
    now = time.monotonic()
    if _idc_creds_cache is not None and now < _idc_creds_expiry:
        return _idc_creds_cache

    session = aioboto3.Session(
        profile_name=get_settings().aws_profile or None, region_name=region
    )
    try:
        async with session.client("sts", region_name=region) as sts:
            resp = await sts.assume_role(
                RoleArn=role_arn,
                RoleSessionName="platform-api-idc",
            )
    except ClientError as exc:
        err = exc.response.get("Error", {})
        raise IdcAPIError(
            err.get("Code", "Unknown"),
            t(
                "aws.idc_assume_role_failed",
                role_arn=role_arn,
                error=err.get("Message", str(exc)),
            ),
        ) from exc
    except BotoCoreError as exc:
        raise IdcAPIError(
            "BotoCoreError",
            t("aws.idc_assume_role_failed", role_arn=role_arn, error=exc),
        ) from exc

    c = resp["Credentials"]
    _idc_creds_cache = {
        "aws_access_key_id": c["AccessKeyId"],
        "aws_secret_access_key": c["SecretAccessKey"],
        "aws_session_token": c["SessionToken"],
    }
    # Expiration 是带 tz 的 datetime; 用其相对 now 的秒数推 monotonic 过期点.
    ttl = (c["Expiration"].timestamp() - time.time()) - _ASSUME_TTL_SKEW_SECONDS
    _idc_creds_expiry = now + max(ttl, 0)
    return _idc_creds_cache


async def _idc_client_kwargs(region: str) -> dict[str, Any]:
    """构造 session.client("identitystore", **kwargs) 的 kwargs.

    配了 IDC_ASSUME_ROLE_ARN → 先 AssumeRole 注入临时凭证 (跨账号);
    否则只带 region (同账号, 走本地 IRSA/Pod Identity/profile 凭证).
    """
    kwargs: dict[str, Any] = {"region_name": region}
    role_arn = get_settings().idc_assume_role_arn
    if role_arn:
        kwargs.update(await _assume_idc_creds(role_arn, region))
    return kwargs


def _normalize_user(u: dict[str, Any]) -> dict[str, Any]:
    """IdC DescribeUser 响应 → 业务侧扁平 dict.

    返回:
        {username, email, display_name, given_name, family_name, user_id}
    """
    emails = u.get("Emails") or []
    primary_email = ""
    for e in emails:
        if e.get("Primary"):
            primary_email = e.get("Value") or ""
            break
    if not primary_email and emails:
        primary_email = emails[0].get("Value") or ""

    name = u.get("Name") or {}
    return {
        "user_id": u.get("UserId") or "",
        "username": u.get("UserName") or "",
        "email": primary_email,
        "display_name": u.get("DisplayName") or "",
        "given_name": name.get("GivenName") or "",
        "family_name": name.get("FamilyName") or "",
    }


async def find_user(q: str) -> dict[str, Any] | None:
    """实时查 IdC 用户. q 是完整 username 或 完整 email.

    按 userName → emails.value 依次精确查, 任一命中即返回 (不靠 "@" 猜:
    很多 IdC 的 userName 本身是邮箱格式, 靠 @ 判断会误把 username 当 email)。

    返回 dict 或 None (未找到).
    AWS 调用失败抛 IdcAPIError.
    """
    s = get_settings()
    if not s.idc_identity_store_id:
        raise IdcAPIError(
            "ConfigMissing",
            t("aws.idc_store_id_missing_env"),
        )

    q_clean = q.strip()
    if not q_clean:
        return None

    # 不靠 "@" 猜 username/email — 很多 IdC 的 userName 本身就是邮箱格式
    # (如 username=alice@example.com, email=alice@example.org), 靠 @ 判断会把
    # username 当 email 查导致搜不到。改为按 userName + emails.value 依次精确查,
    # 先命中先用。
    attribute_paths = ["userName", "emails.value"]

    idc_region = s.idc_region or s.aws_region
    session = aioboto3.Session(
        profile_name=s.aws_profile or None, region_name=idc_region
    )
    client_kwargs = await _idc_client_kwargs(idc_region)
    try:
        async with session.client("identitystore", **client_kwargs) as client:
            # Step 1: 依次按 userName / emails.value 查 UserId, 任一命中即用
            user_id = None
            for attribute_path in attribute_paths:
                try:
                    resp = await client.get_user_id(
                        IdentityStoreId=s.idc_identity_store_id,
                        AlternateIdentifier={
                            "UniqueAttribute": {
                                "AttributePath": attribute_path,
                                "AttributeValue": q_clean,
                            }
                        },
                    )
                    user_id = resp["UserId"]
                    break
                except ClientError as exc:
                    code = exc.response.get("Error", {}).get("Code", "")
                    msg = exc.response.get("Error", {}).get("Message", str(exc))
                    if code == "ResourceNotFoundException":
                        # 区分"用户不存在"vs"identity store 不存在/region 配错".
                        # store 不存在时 Message 含 store 相关字样, 不能吞成 None
                        # (那会假装"没这个人"掩盖配置错误)。
                        if "store" in msg.lower():
                            raise IdcAPIError(
                                "IdentityStoreNotFound",
                                t(
                                    "aws.idc_store_unreachable",
                                    store_id=s.idc_identity_store_id,
                                    region=idc_region,
                                    error=msg,
                                ),
                            ) from exc
                        # 这个 attribute 没匹配到 → 试下一个
                        continue
                    raise IdcAPIError(code or "Unknown", msg) from exc

            if user_id is None:
                logger.info(
                    "idc.find_user.not_found",
                    q=q_clean, attrs=",".join(attribute_paths),
                )
                return None

            # Step 2: DescribeUser 拿完整信息
            user_resp = await client.describe_user(
                IdentityStoreId=s.idc_identity_store_id,
                UserId=user_id,
            )
    except IdcAPIError:
        raise
    except ClientError as exc:
        err = exc.response.get("Error", {})
        raise IdcAPIError(
            err.get("Code", "Unknown"), err.get("Message", str(exc))
        ) from exc
    except BotoCoreError as exc:
        raise IdcAPIError("BotoCoreError", str(exc)) from exc

    user_resp.pop("ResponseMetadata", None)
    normalized = _normalize_user(user_resp)
    logger.info(
        "idc.find_user.ok",
        q=q_clean, username=normalized["username"], email=normalized["email"],
    )
    return normalized


async def describe_user_by_id(user_id: str) -> dict[str, Any] | None:
    """已知 IdC UserId (UUID) 拿用户全部信息. 用于反查."""
    s = get_settings()
    if not s.idc_identity_store_id:
        raise IdcAPIError("ConfigMissing", t("aws.idc_store_id_missing"))
    idc_region = s.idc_region or s.aws_region
    session = aioboto3.Session(
        profile_name=s.aws_profile or None, region_name=idc_region
    )
    client_kwargs = await _idc_client_kwargs(idc_region)
    try:
        async with session.client("identitystore", **client_kwargs) as client:
            resp = await client.describe_user(
                IdentityStoreId=s.idc_identity_store_id,
                UserId=user_id,
            )
    except ClientError as exc:
        err = exc.response.get("Error", {})
        if err.get("Code") == "ResourceNotFoundException":
            return None
        raise IdcAPIError(
            err.get("Code", "Unknown"), err.get("Message", str(exc))
        ) from exc
    except BotoCoreError as exc:
        raise IdcAPIError("BotoCoreError", str(exc)) from exc

    resp.pop("ResponseMetadata", None)
    return _normalize_user(resp)
