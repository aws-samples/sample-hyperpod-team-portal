"""Cognito UserPool + Client + Domain (平台登录).

callback URL 部署后回填 (ALB 域名起来才知道); 先放占位.
"""

from aws_cdk import Duration
from aws_cdk import aws_cognito as cognito
from constructs import Construct


class CognitoConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        domain_prefix: str,
        alb_domain: str = "",
    ) -> None:
        super().__init__(scope, cid)

        # callback: albDomainName 非空 → 直接拼真实域名 (deploy 即对, 免回填);
        # 空 → localhost 占位 (联调期用 cognito-callback.sh 回填)。
        if alb_domain:
            callback_urls = [f"https://{alb_domain}/auth/callback"]
        else:
            callback_urls = ["https://localhost/auth/callback"]

        # ⚠️ construct id 从 "UserPool" → "UserPoolV2": 强制 CFN 删旧池 + 建新池。
        # 用途: 旧池 email mutable=False (无法原地改), 联合登录二次同步报 email cannot be
        # updated; 新池带 mutable=True。改 logical id 是一次性迁移, 定后勿再改回。
        # 连带: 新池换 UserPoolId/ClientId, 需重配 IdC SAML application (ACS/Entity ID)
        # + 重建 SAML provider + 关联 IdP。
        pool = cognito.UserPool(
            self, "UserPoolV2",
            user_pool_name=domain_prefix,  # 含 projectName, 便辨识
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            standard_attributes=cognito.StandardAttributes(
                # mutable=True: IdC/SAML 联合登录时 Cognito 每次登录用 IdP 传来的 email
                # 同步联合用户属性; 设 False 会在二次登录时报 "email cannot be updated"。
                # (mutable 建池即定死, 改此值需重建用户池)
                email=cognito.StandardAttribute(required=True, mutable=True),
            ),
        )

        client = pool.add_client(
            "WebClient",
            generate_secret=False,  # SPA PKCE, 无 client secret
            # Token 有效期: ID/Access token 默认 1h, 抬到 1 天 (Cognito 上限 24h),
            # 减少用户联调期频繁重登。refresh token 30 天 (默认), 到期前静默续期。
            id_token_validity=Duration.days(1),
            access_token_validity=Duration.days(1),
            refresh_token_validity=Duration.days(30),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                # albDomainName 拼的真实 callback (deploy 即对); 空则 localhost 占位。
                callback_urls=callback_urls,
            ),
        )

        domain = pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=domain_prefix),
        )

        self.user_pool = pool
        self.user_pool_id = pool.user_pool_id
        self.user_pool_arn = pool.user_pool_arn
        self.client_id = client.user_pool_client_id
        # ⚠️ domain.domain_name 只返前缀 (如 deploy-0611-123456789012)。后端 / 前端
        # 需要完整 Hosted UI 域名, 否则 authorize URL 缺后缀 → 浏览器 "Server Not Found"。
        # 拼成 <prefix>.auth.<region>.amazoncognito.com。
        from aws_cdk import Stack
        region = Stack.of(self).region
        self.domain = f"{domain.domain_name}.auth.{region}.amazoncognito.com"
