# CloudFront + VPC Origin + Internal ALB Deployment

**English** | [简体中文](internal-alb-with-domainname.zh-CN.md)

## Architecture overview

```
User browser
    │
    ▼
Route 53 (example.com)
    │  A Record (Alias → CloudFront)
    ▼
CloudFront Distribution (HTTPS, ACM certificate in us-east-1)
    │  VPC Origin (AWS backbone network, not the public internet)
    ▼
Internal ALB (inside the VPC, not exposed to the internet)
    │
    ▼
EKS Platform Pods (platform-api / frontend / worker)
```

## Benefits

- ✅ The ALB is not exposed to the internet, so the attack surface is minimal
- ✅ CloudFront provides global edge acceleration plus built-in DDoS protection (Shield Standard)
- ✅ HTTPS terminates at CloudFront, so the backend can use plain HTTP
- ✅ VPC Origin traffic travels over the AWS backbone network, with low latency

## Prerequisites

- The internal ALB is already deployed (created by the EKS Ingress)
- The VPC has private subnets
- The domain is hosted in Route 53
- IAM permissions: CloudFront / ACM / Route 53 / ELBv2

---

## Step 1 · Request ACM certificates

> ⚠️ CloudFront requires the certificate to be in **us-east-1**; the certificate used by the ALB must be in the ALB's Region.

```bash
DOMAIN="example.com"
REGION_ALB="us-west-2"   # Region where the ALB runs

# 1a. For CloudFront (must be us-east-1)
CF_CERT_ARN=$(aws acm request-certificate \
  --domain-name "$DOMAIN" \
  --subject-alternative-names "*.$DOMAIN" \
  --validation-method DNS \
  --region us-east-1 \
  --query 'CertificateArn' --output text)
echo "CloudFront certificate: $CF_CERT_ARN"

# 1b. For the ALB (ALB Region)
ALB_CERT_ARN=$(aws acm request-certificate \
  --domain-name "$DOMAIN" \
  --subject-alternative-names "*.$DOMAIN" \
  --validation-method DNS \
  --region $REGION_ALB \
  --query 'CertificateArn' --output text)
echo "ALB certificate: $ALB_CERT_ARN"
```

## Step 2 · DNS validation (added to Route 53 automatically)

```bash
# Get the validation record (both certificates share the same CNAME)
VALIDATION=$(aws acm describe-certificate --certificate-arn $CF_CERT_ARN --region us-east-1 \
  --query 'Certificate.DomainValidationOptions[0].ResourceRecord.{Name:Name,Value:Value}' --output json)

CNAME_NAME=$(echo $VALIDATION | python3 -c "import json,sys;print(json.load(sys.stdin)['Name'])")
CNAME_VALUE=$(echo $VALIDATION | python3 -c "import json,sys;print(json.load(sys.stdin)['Value'])")

# Look up the hosted zone ID
ZONE_ID=$(aws route53 list-hosted-zones-by-name --dns-name "$DOMAIN" \
  --query "HostedZones[?Name=='${DOMAIN}.'].Id" --output text | sed 's|/hostedzone/||')

# Add the validation CNAME
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

# Wait for certificate validation to complete (1-5 minutes)
aws acm wait certificate-validated --certificate-arn $CF_CERT_ARN --region us-east-1
echo "✓ Certificate validated"
```

## Step 3 · Get the internal ALB details

```bash
REGION="us-west-2"

# Get the ALB ARN and DNS name
ALB_DNS="<internal-alb-dns>"   # Get this from kubectl get ingress
ALB_ARN=$(aws elbv2 describe-load-balancers --region $REGION \
  --query "LoadBalancers[?DNSName=='$ALB_DNS'].LoadBalancerArn" --output text)
echo "ALB ARN: $ALB_ARN"
echo "ALB DNS: $ALB_DNS"
```

## Step 4 · Create the VPC Origin

```bash
# Create a VPC Origin that points to the internal ALB
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

# Wait for deployment (about 5-8 minutes)
echo "Waiting for the VPC Origin to deploy..."
while true; do
  STATUS=$(aws cloudfront get-vpc-origin --id $VPC_ORIGIN --query 'VpcOrigin.Status' --output text)
  echo "  Status: $STATUS"
  [ "$STATUS" = "Deployed" ] && break
  sleep 20
done
echo "✓ VPC Origin Deployed"
```

## Step 5 · Create the CloudFront distribution

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

# Record the distribution details
CF_DOMAIN=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Aliases.Items[0]=='$DOMAIN'].DomainName" --output text)
CF_ID=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Aliases.Items[0]=='$DOMAIN'].Id" --output text)
echo "Distribution ID: $CF_ID"
echo "CloudFront Domain: $CF_DOMAIN"
```

## Step 6 · Point a Route 53 A record at CloudFront

```bash
# The hosted zone ID for CloudFront is always Z2FDTNDATAQYW2
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

## Step 7 · (Optional) WebSocket support

If the application needs WebSocket (for example, the VS Code Web IDE), add an additional cache behavior:

```bash
# Get the current distribution config
aws cloudfront get-distribution-config --id $CF_ID --output json > /tmp/cf-config.json
ETAG=$(python3 -c "import json; print(json.load(open('/tmp/cf-config.json'))['ETag'])")

# Add a CacheBehavior for the WebSocket path (no caching + forward all headers)
# PathPattern: "/api/v1/dev-instances/*/proxy/*"
# CachePolicyId: 4135ea2d-6df8-44a3-9df3-4b5a84be39ad (CachingDisabled)
# OriginRequestPolicyId: 216adef6-5c7f-47e4-b989-5492eafa07d3 (AllViewer)
# Required fields: SmoothStreaming, FieldLevelEncryptionId, LambdaFunctionAssociations, FunctionAssociations

# Update the distribution
aws cloudfront update-distribution --id $CF_ID --if-match $ETAG \
  --distribution-config file:///tmp/cf-config-updated.json
```

> ⚠️ **Known limitation**: VS Code Web (code-server) hard-codes the WebSocket address to the pod's private IP. Even if CloudFront proxies WebSocket correctly, the browser still cannot connect directly to a private IP inside the VPC. We recommend using an SSM tunnel or VS Code Remote-SSH instead.

---

## Known issues and caveats

| Issue | Description | Resolution |
|------|------|------|
| WebSocket 1006 | code-server hard-codes the pod IP as the WS address | Use an SSM tunnel or VS Code Remote-SSH |
| VPC Origin deploys slowly | Takes 5-8 minutes after creation to become Deployed | Wait before associating it with the distribution |
| CloudFront updates slowly | Distribution changes take 3-15 minutes to propagate globally | The old configuration keeps serving while the status is InProgress |
| Required CacheBehavior fields | update-distribution fails with InvalidArgument if fields are missing | Must include SmoothStreaming / FieldLevelEncryptionId / Lambda/FunctionAssociations |
| VpcOriginConfig casing | In the CLI JSON it is `VpcOriginConfig` + `VpcOriginId` (not all-caps VPC) | Follow the AWS CLI parameter validation messages exactly |

---

## Resource inventory (record after deployment; example values)

| Resource | Value |
|------|-----|
| Domain | example.com |
| Route 53 Hosted Zone | Z0123456789EXAMPLE |
| ACM certificate (us-east-1, CloudFront) | arn:aws:acm:us-east-1:123456789012:certificate/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx |
| ACM certificate (us-west-2, ALB) | arn:aws:acm:us-west-2:123456789012:certificate/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx |
| VPC Origin ID | vo_EXAMPLE0123456789 |
| CloudFront Distribution ID | E1234567890ABC |
| CloudFront Domain | d1234567890abc.cloudfront.net |
| Internal ALB | internal-k8s-platform-xxxxxxxxxx-1234567890.us-west-2.elb.amazonaws.com |

---

## Cognito callback configuration

With the CloudFront setup, set the Cognito callback URL to:
```
https://example.com/auth/callback
```

To also support local development:
```bash
CALLBACK_URL=https://example.com/auth/callback \
EXTRA_CALLBACKS="http://localhost:8080/auth/callback" \
./deploy/cognito-callback.sh
```
