# 内网域名 + 内网证书 + ALB HTTPS 部署

[English](internal-domain-deployment.md) | **简体中文**

> **目标**：给平台前端绑一个内网域名，让用户在 VPC / VPN 内通过 `https://<内网域名>` 访问，
> 并支持 ALB 层 Cognito (IdC) 登录。
>
> **为什么必须 HTTPS（关键背景）**：前端登录走 PKCE flow，要用浏览器的 Web Crypto API
> (`crypto.subtle.digest` 算 SHA-256 code_challenge)。`crypto.subtle` **只在安全上下文
> (HTTPS / localhost) 可用**；HTTP 下它是 `undefined`，会报
> `Cannot read properties of undefined (reading 'digest')`。所以"页面是 HTTPS 且浏览器信任
> 证书"是登录能跑通的硬前提 —— 这也是为什么下面要折腾内网 CA + 证书 + 浏览器信任。
>
> **架构约束**：ALB 是 `internal`（仅 VPC 内可访问），用户须在 VPN / 跳板机 / 同 VPC 环境，
> 且该环境能出公网到 Cognito Hosted UI。Cognito App Client 的回调 URL 必须填内网域名的
> `https://<内网域名>/oauth2/idpresponse`。

---

## 1. 申请内网域名（Route53）

在 Route53 建一个 **Private Hosted Zone（私有托管区）**，并**关联到 EKS 集群所在的 VPC**
（只有关联了 VPC，VPC 内 / VPN 进来的机器才能解析这个内网域名）。

控制台：Route53 → Hosted zones → Create hosted zone
- Domain name：如 `internal.company.com`（或直接用最终域名的父域）
- Type：**Private hosted zone**
- VPC：选 EKS 所在 region（us-west-2）+ EKS 的 VPC ID

CLI：
```bash
aws route53 create-hosted-zone \
  --name internal.company.com \
  --vpc VPCRegion=us-west-2,VPCId=<eks-vpc-id> \
  --hosted-zone-config PrivateZone=true \
  --caller-reference $(date +%s)
```
> 拿 EKS 的 VPC：`aws eks describe-cluster --name <集群名> --region us-west-2 --query 'cluster.resourcesVpcConfig.vpcId'`

---

## 2. 申请 Private Certificate Authority（ACM PCA）

因为是内网域名，用 **ACM Private CA** 自建内网 CA（公网 CA 无法为内网域名签发）。

控制台：AWS Private CA → Create a private CA
- CA type：**Root CA**（自建根；若已有上级 CA 也可建 Subordinate）
- 填 CA 主体信息（Organization / CN 等）
- Key algorithm：**RSA 2048**（或 ECDSA；**不要 ED25519**，ALB 不支持）

**⚠️ 关键最后一步**：CA 创建后状态是 `Pending certificate`，必须执行
**Actions → Install CA certificate** 才能让 Status 变成 **Active**。
（Root CA 这一步是自签安装；不做这步 CA 无法签发任何证书。）

---

## 3. 为内网域名申请内网证书（ACM）

用上面的 Private CA 给内网域名签一张证书，放进 **ACM**（和 ALB 同 region：us-west-2）。

控制台：ACM → Request certificate → **Request a private certificate**
- Certificate authority：选第 2 步建的 Private CA
- Domain name：**填最终的内网域名**，如 `hyperpod.internal.company.com`
  （证书 CN/SAN 必须包含这个域名，否则浏览器报域名不匹配）
- 签发后状态应为 **Issued**

**⚠️ 必须和 ALB 同 region（us-west-2）**，否则第 5 步 ALB listener 下拉里**选不出来**这张证书。
（ACM 证书是 region 级的。）

> 验证：`aws acm list-certificates --region us-west-2` 应能看到，且 Status=ISSUED、
> KeyAlgorithm 是 RSA/ECDSA（非 ED25519）。

---

## 4. 修改内网域名 DNS，加 A 记录 Alias 指向 ALB

先确保平台 Ingress 已部署、ALB 已生成（拿到 ALB 的 DNS 名，形如
`internal-k8s-platform-...us-west-2.elb.amazonaws.com`）。

在第 1 步的 Private Hosted Zone 里加一条记录：
- Record name：`hyperpod.internal.company.com`
- Record type：**A**
- **打开 Alias 开关**（关键！普通 A 记录只能填 IPv4，直接填 ALB 域名会报
  `ARRDATAIllegalIPv4Address`）
- Route traffic to：**Alias to Application and Classic Load Balancer** → Region us-west-2 → 选你的 ALB

CLI：
```bash
aws route53 change-resource-record-sets --hosted-zone-id <私有区ID> --change-batch '{
  "Changes": [{
    "Action": "UPSERT",
    "ResourceRecordSet": {
      "Name": "hyperpod.internal.company.com",
      "Type": "A",
      "AliasTarget": {
        "HostedZoneId": "Z1H1FL5HABSF5",
        "DNSName": "<ALB-DNS-名>",
        "EvaluateTargetHealth": true
      }
    }
  }]
}'
```
> `Z1H1FL5HABSF5` 是 **us-west-2 ALB 的固定 HostedZoneId**（所有 us-west-2 的 ALB 共用，
> AWS 文档给定值）。不确定可用 `aws elbv2 describe-load-balancers` 看 ALB 的 `CanonicalHostedZoneId` 核对。
> 外层 `--hosted-zone-id` 填的是你的**私有托管区** ID，两者不要混。

---

## 5. 导出 Private CA 的根证书 + 证书链（PEM）

浏览器要信任的是**内网 CA 的根证书**，不是 ALB 上那张叶子证书。从 ACM Private CA 导出根 CA：

控制台：AWS Private CA → 选你的 CA → **CA certificate** 标签 → 复制 / 下载证书 PEM。

CLI：
```bash
# 导出 Private CA 的 CA 证书 (根证书)
aws acm-pca get-certificate-authority-certificate \
  --certificate-authority-arn <PCA-ARN> --region us-west-2 \
  --output text > internal-root-ca.pem
```
保存为 `internal-root-ca.pem`，下一步装进各机器信任库。

> **证书链完整性（常见坑）**：ALB 上的证书链必须包含中间 CA（叶子→中间→根），否则即使
> 装了根 CA，浏览器也验不过链。用 Private CA 签发 + ACM 部署一般链是完整的。

---

## 6. Windows 安装 Trusted Root Certificate

把根 CA（第 6 步的 `internal-root-ca.pem`/`.crt`）装进
**受信任的根证书颁发机构 → 本地计算机**。

方法 A（图形界面）：
1. `Win + R` → `certlm.msc`（本地计算机证书，需管理员）
2. 受信任的根证书颁发机构 → 证书 → 右键 → 所有任务 → 导入
3. 选根 CA 文件，存储位置确认是"受信任的根证书颁发机构"

方法 B（管理员 PowerShell）：
```powershell
Import-Certificate -FilePath "C:\path\internal-root-ca.crt" -CertStoreLocation Cert:\LocalMachine\Root
```
（CMD 等价：`certutil -addstore -f "Root" "C:\path\internal-root-ca.crt"`）

装完**完全关闭并重开浏览器**（Chrome/Edge 用 Windows 系统信任库；进程要彻底退出重启）。

验证：
```powershell
Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Subject -like "*<你的CA名>*" }
```
> Firefox 例外：它有独立信任库，需在 Firefox 设置里单独导入。

---

## 7. Mac 信任这个根证书

把根 CA 装进系统钥匙串并设为"始终信任"：

图形界面：
1. 双击 `internal-root-ca.pem` → 钥匙串访问 → 加到 **系统(System)** 钥匙串
2. 找到该 CA 证书 → 双击 → 展开"信任" → **使用此证书时：始终信任**

命令行：
```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain internal-root-ca.pem
```
装完重开浏览器。

---

## 9. 打开浏览器验证

1. 访问 `https://hyperpod.internal.company.com` → 地址栏应是**绿锁 / 安全**（不再 Not Secure）
2. 安全上下文成立 → `crypto.subtle` 可用 → PKCE 的 `digest` 报错消失
3. 未登录会被 ALB 重定向到 **Cognito Hosted UI → IdC** 登录
4. 登录后回调 `/oauth2/idpresponse` → 进入平台

**若仍 Not Secure，点地址栏警告看错误码定位：**
- `ERR_CERT_AUTHORITY_INVALID` → 根 CA 没装对位置 / 装的是叶子证书而非根 CA
- `ERR_CERT_COMMON_NAME_INVALID` → 证书 SAN 未包含该内网域名（回第 3 步重签）
- 证书链相关 → ALB 证书链缺中间 CA（回第 6 步检查链完整性）

**全员推广**：手动装根 CA 只适合调试。面向所有用户应由 IT 通过
**AD 组策略(GPO) / MDM / Jamf** 把内网根 CA 统一分发到员工机器信任库。
