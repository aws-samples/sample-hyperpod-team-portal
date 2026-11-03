# CloudFront + VPC Origin + Internal ALB 部署方案

[English](internal-alb-with-domainname.md) | **简体中文**

## 架构概览

```
用户浏览器
    │
    ▼
Route 53 (example.com)
    │  A Record (Alias → CloudFront)
    ▼
CloudFront Distribution (HTTPS, ACM 证书 us-east-1)
    │  VPC Origin (AWS 骨干网, 不走公网)
    ▼
Internal ALB (VPC 内, 不暴露公网)
    │
    ▼
EKS Platform Pods (platform-api / frontend / worker)
```

## 优势

- ✅ ALB 不暴露公网, 攻击面极小
- ✅ CloudFront 全球边缘加速 + 自带 DDoS 防护 (Shield Standard)
- ✅ HTTPS 终结在 CloudFront, 后端走 HTTP 即可
- ✅ VPC Origin 走 AWS 骨干网, 延迟低

## 前提条件

- Internal ALB 已部署（EKS Ingress 创建）
- VPC 内有私有子网
- 域名已在 Route 53 托管
- IAM 权限: CloudFront / ACM / Route 53 / ELBv2

---

## Step 1 · 申请 ACM 证书

> ⚠️ CloudFront 要求证书必须在 **us-east-1**; ALB 用的证书在 ALB 所在 region.

```bash
DOMAIN="example.com"
REGION_ALB="us-west-2"   # ALB 所在 region

# 1a. CloudFront 用 (必须 us-east-1)
CF_CERT_ARN=$(aws acm request-certificate \
  --domain-name "$DOMAIN" \
  --subject-alternative-names "*.$DOMAIN" \
  --validation-method DNS \
  --region us-east-1 \
  --query 'CertificateArn' --output text)
echo "CloudFront 证书: $CF_CERT_ARN"

# 1b. ALB 用 (ALB region)
ALB_CERT_ARN=$(aws acm request-certificate \
  --domain-name "$DOMAIN" \
  --subject-alternative-names "*.$DOMAIN" \
  --validation-method DNS \
  --region $REGION_ALB \
  --query 'CertificateArn' --output text)
echo "ALB 证书: $ALB_CERT_ARN"
```

## Step 2 · DNS 验证 (自动添加到 Route 53)

```bash
# 获取验证记录 (两个证书共用同一条 CNAME)
VALIDATION=$(aws acm describe-certificate --certificate-arn $CF_CERT_ARN --region us-east-1 \
  --query 'Certificate.DomainValidationOptions[0].ResourceRecord.{Name:Name,Value:Value}' --output json)

CNAME_NAME=$(echo $VALIDATION | python3 -c "import json,sys;print(json.load(sys.stdin)['Name'])")
CNAME_VALUE=$(echo $VALIDATION | python3 -c "import json,sys;print(json.load(sys.stdin)['Value'])")

# 找到 Hosted Zone ID
ZONE_ID=$(aws route53 list-hosted-zones-by-name --dns-name "$DOMAIN" \
  --query "HostedZones[?Name=='${DOMAIN}.'].Id" --output text | sed 's|/hostedzone/||')

# 添加验证 CNAME
aws route53 change-resource-record-sets --hosted-zone-id $ZONE_ID --change-batch "{
  \"Changes\": [{
    \"Action\": \"UPSERT\",
    \"ResourceRecordSet\": {
      \"Name\": \"$CNAME_NAME\",
      \"Type\": \"CNAME\",
      \"TTL\": 300,
      \"ResourceRecords\": [{\"Value\": \"$CNAME_VALUE\"}]
    }
  }]
}"

# 等待证书验证通过 (1-5 分钟)
aws acm wait certificate-validated --certificate-arn $CF_CERT_ARN --region us-east-1
echo "✓ 证书已验证"
```

## Step 3 · 获取 Internal ALB 信息

```bash
REGION="us-west-2"

# 获取 ALB ARN 和 DNS
ALB_DNS="<internal-alb-dns>"   # 从 kubectl get ingress 获取
ALB_ARN=$(aws elbv2 describe-load-balancers --region $REGION \
  --query "LoadBalancers[?DNSName=='$ALB_DNS'].LoadBalancerArn" --output text)
echo "ALB ARN: $ALB_ARN"
echo "ALB DNS: $ALB_DNS"
```

## Step 4 · 创建 VPC Origin

```bash
# 创建 VPC Origin 指向 Internal ALB
VPC_ORIGIN=$(aws cloudfront create-vpc-origin \
  --vpc-origin-endpoint-config "{
    \"Name\": \"platform-alb-origin\",
    \"Arn\": \"$ALB_ARN\",
    \"HTTPPort\": 80,
    \"HTTPSPort\": 443,
    \"OriginProtocolPolicy\": \"http-only\",
    \"OriginSslProtocols\": {\"Quantity\": 1, \"Items\": [\"TLSv1.2\"]}
  }" --query 'VpcOrigin.Id' --output text)
echo "VPC Origin ID: $VPC_ORIGIN"

# 等待部署 (约 5-8 分钟)
echo "等待 VPC Origin 部署..."
while true; do
  STATUS=$(aws cloudfront get-vpc-origin --id $VPC_ORIGIN --query 'VpcOrigin.Status' --output text)
  echo "  Status: $STATUS"
  [ "$STATUS" = "Deployed" ] && break
  sleep 20
done
echo "✓ VPC Origin Deployed"
```

## Step 5 · 创建 CloudFront Distribution

```bash
aws cloudfront create-distribution --distribution-config "{
  \"CallerReference\": \"$(date +%s)\",
  \"Comment\": \"Platform via VPC Origin\",
  \"Enabled\": true,
  \"Aliases\": {
    \"Quantity\": 1,
    \"Items\": [\"$DOMAIN\"]
  },
  \"ViewerCertificate\": {
    \"ACMCertificateArn\": \"$CF_CERT_ARN\",
    \"SSLSupportMethod\": \"sni-only\",
    \"MinimumProtocolVersion\": \"TLSv1.2_2021\"
  },
  \"DefaultCacheBehavior\": {
    \"TargetOriginId\": \"platform-alb\",
    \"ViewerProtocolPolicy\": \"redirect-to-https\",
    \"AllowedMethods\": {
      \"Quantity\": 7,
      \"Items\": [\"GET\",\"HEAD\",\"OPTIONS\",\"PUT\",\"POST\",\"PATCH\",\"DELETE\"],
      \"CachedMethods\": {\"Quantity\": 2, \"Items\": [\"GET\",\"HEAD\"]}
    },
    \"CachePolicyId\": \"4135ea2d-6df8-44a3-9df3-4b5a84be39ad\",
    \"OriginRequestPolicyId\": \"216adef6-5c7f-47e4-b989-5492eafa07d3\",
    \"Compress\": true
  },
  \"Origins\": {
    \"Quantity\": 1,
    \"Items\": [{
      \"Id\": \"platform-alb\",
      \"DomainName\": \"$ALB_DNS\",
      \"VpcOriginConfig\": {
        \"VpcOriginId\": \"$VPC_ORIGIN\",
        \"OriginKeepaliveTimeout\": 5,
        \"OriginReadTimeout\": 30
      }
    }]
  },
  \"PriceClass\": \"PriceClass_All\",
  \"HttpVersion\": \"http2and3\"
}"

# 记录 Distribution 信息
CF_DOMAIN=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Aliases.Items[0]=='$DOMAIN'].DomainName" --output text)
CF_ID=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Aliases.Items[0]=='$DOMAIN'].Id" --output text)
echo "Distribution ID: $CF_ID"
echo "CloudFront Domain: $CF_DOMAIN"
```

## Step 6 · Route 53 A 记录指向 CloudFront

```bash
# CloudFront 的 Hosted Zone ID 固定为 Z2FDTNDATAQYW2
aws route53 change-resource-record-sets --hosted-zone-id $ZONE_ID --change-batch "{
  \"Changes\": [{
    \"Action\": \"UPSERT\",
    \"ResourceRecordSet\": {
      \"Name\": \"$DOMAIN\",
      \"Type\": \"A\",
      \"AliasTarget\": {
        \"HostedZoneId\": \"Z2FDTNDATAQYW2\",
        \"DNSName\": \"$CF_DOMAIN\",
        \"EvaluateTargetHealth\": false
      }
    }
  }]
}"
echo "✓ Route 53 A record → CloudFront"
```

## Step 7 · (可选) WebSocket 支持

如果应用有 WebSocket 需求 (如 VS Code Web IDE), 需要添加额外的 CacheBehavior:

```bash
# 获取当前 distribution config
aws cloudfront get-distribution-config --id $CF_ID --output json > /tmp/cf-config.json
ETAG=$(python3 -c "import json; print(json.load(open('/tmp/cf-config.json'))['ETag'])")

# 添加 WebSocket 路径的 CacheBehavior (不缓存 + 转发所有 headers)
# PathPattern: "/api/v1/dev-instances/*/proxy/*"
# CachePolicyId: 4135ea2d-6df8-44a3-9df3-4b5a84be39ad (CachingDisabled)
# OriginRequestPolicyId: 216adef6-5c7f-47e4-b989-5492eafa07d3 (AllViewer)
# 必须包含字段: SmoothStreaming, FieldLevelEncryptionId, LambdaFunctionAssociations, FunctionAssociations

# 更新 distribution
aws cloudfront update-distribution --id $CF_ID --if-match $ETAG \
  --distribution-config file:///tmp/cf-config-updated.json
```

> ⚠️ **已知限制**: VS Code Web (code-server) 会将 WebSocket 地址硬编码为 pod 内网 IP, 即使 CloudFront 正确代理 WebSocket, 浏览器仍无法直连 VPC 内网 IP. 推荐使用 SSM 隧道或 VSCode Remote-SSH 方案.

---

## 已知问题 & 注意事项

| 问题 | 说明 | 解决 |
|------|------|------|
| WebSocket 1006 | code-server 硬编码 pod IP 作为 WS 地址 | 用 SSM 隧道或 VSCode Remote-SSH |
| VPC Origin 部署慢 | 创建后需 5-8 分钟变为 Deployed | 等待后再关联 Distribution |
| CloudFront 更新慢 | Distribution 变更需 3-15 分钟全球生效 | InProgress 期间旧配置仍可用 |
| CacheBehavior 必填字段 | update-distribution 时缺字段报 InvalidArgument | 必须包含 SmoothStreaming / FieldLevelEncryptionId / Lambda/FunctionAssociations |
| VpcOriginConfig 大小写 | CLI JSON 中是 `VpcOriginConfig` + `VpcOriginId` (非 VPC 全大写) | 严格按 AWS CLI 参数校验提示 |

---

## 资源清单 (部署后记录, 示例值)

| 资源 | 值 |
|------|-----|
| 域名 | example.com |
| Route 53 Hosted Zone | Z0123456789EXAMPLE |
| ACM 证书 (us-east-1, CloudFront) | arn:aws:acm:us-east-1:123456789012:certificate/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx |
| ACM 证书 (us-west-2, ALB) | arn:aws:acm:us-west-2:123456789012:certificate/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx |
| VPC Origin ID | vo_EXAMPLE0123456789 |
| CloudFront Distribution ID | E1234567890ABC |
| CloudFront Domain | d1234567890abc.cloudfront.net |
| Internal ALB | internal-k8s-platform-xxxxxxxxxx-1234567890.us-west-2.elb.amazonaws.com |

---

## Cognito 回调配置

CloudFront 方案下, Cognito callback URL 配为:
```
https://example.com/auth/callback
```

如需同时支持本地开发:
```bash
CALLBACK_URL=https://example.com/auth/callback \
EXTRA_CALLBACKS="http://localhost:8080/auth/callback" \
./deploy/cognito-callback.sh
```
