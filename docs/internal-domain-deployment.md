# Internal Domain + Internal Certificate + ALB HTTPS Deployment

**English** | [简体中文](internal-domain-deployment.zh-CN.md)

> **Goal**: Bind an internal domain to the platform frontend so that users inside the VPC / VPN can access it at `https://<internal-domain>`,
> with Cognito (IdC) sign-in supported at the ALB layer.
>
> **Why HTTPS is mandatory (key background)**: Frontend sign-in uses the PKCE flow, which relies on the browser's Web Crypto API
> (`crypto.subtle.digest` computes the SHA-256 code_challenge). `crypto.subtle` is **only available in a secure context
> (HTTPS / localhost)**; over HTTP it is `undefined`, and you get
> `Cannot read properties of undefined (reading 'digest')`. So "the page is served over HTTPS and the browser trusts the
> certificate" is a hard prerequisite for sign-in to work — which is why the steps below go through the trouble of an internal CA + certificate + browser trust.
>
> **Architecture constraints**: The ALB is `internal` (reachable only from within the VPC). Users must be on a VPN / bastion host / in the same VPC,
> and that environment must have outbound internet access to the Cognito Hosted UI. The callback URL of the Cognito App Client must be the internal domain's
> `https://<internal-domain>/oauth2/idpresponse`.

---

## 1. Register an Internal Domain (Route53)

In Route53, create a **Private Hosted Zone** and **associate it with the VPC where the EKS cluster runs**
(only after the VPC is associated can machines inside the VPC / connected over VPN resolve this internal domain).

Console: Route53 → Hosted zones → Create hosted zone
- Domain name: e.g. `internal.company.com` (or the parent domain of the final domain)
- Type: **Private hosted zone**
- VPC: select the EKS region (us-west-2) + the EKS VPC ID

CLI:
```bash
aws route53 create-hosted-zone \
  --name internal.company.com \
  --vpc VPCRegion=us-west-2,VPCId=<eks-vpc-id> \
  --hosted-zone-config PrivateZone=true \
  --caller-reference $(date +%s)
```
> Get the EKS VPC: `aws eks describe-cluster --name <cluster-name> --region us-west-2 --query 'cluster.resourcesVpcConfig.vpcId'`

---

## 2. Create a Private Certificate Authority (ACM PCA)

Because this is an internal domain, use **ACM Private CA** to set up your own internal CA (public CAs cannot issue certificates for internal domains).

Console: AWS Private CA → Create a private CA
- CA type: **Root CA** (your own root; if you already have a parent CA, you can create a Subordinate CA instead)
- Fill in the CA subject information (Organization / CN, etc.)
- Key algorithm: **RSA 2048** (or ECDSA; **not ED25519**, which ALB does not support)

**⚠️ Critical final step**: After the CA is created, its status is `Pending certificate`. You must run
**Actions → Install CA certificate** for the Status to become **Active**.
(For a Root CA, this step installs a self-signed certificate; without it, the CA cannot issue any certificates.)

---

## 3. Request an Internal Certificate for the Internal Domain (ACM)

Use the Private CA above to issue a certificate for the internal domain and store it in **ACM** (in the same region as the ALB: us-west-2).

Console: ACM → Request certificate → **Request a private certificate**
- Certificate authority: select the Private CA created in step 2
- Domain name: **enter the final internal domain**, e.g. `hyperpod.internal.company.com`
  (the certificate CN/SAN must include this domain, otherwise the browser reports a domain mismatch)
- After issuance, the status should be **Issued**

**⚠️ It must be in the same region as the ALB (us-west-2)**, otherwise this certificate **will not appear** in the ALB listener dropdown in step 5.
(ACM certificates are regional.)

> Verify: `aws acm list-certificates --region us-west-2` should list it, with Status=ISSUED and
> KeyAlgorithm RSA/ECDSA (not ED25519).

---

## 4. Update the Internal Domain DNS: Add an A Record Alias Pointing to the ALB

First make sure the platform Ingress is deployed and the ALB has been created (get the ALB DNS name, which looks like
`internal-k8s-platform-...us-west-2.elb.amazonaws.com`).

In the Private Hosted Zone from step 1, add a record:
- Record name: `hyperpod.internal.company.com`
- Record type: **A**
- **Turn on the Alias toggle** (critical! A plain A record only accepts IPv4 addresses; entering the ALB domain directly fails with
  `ARRDATAIllegalIPv4Address`)
- Route traffic to: **Alias to Application and Classic Load Balancer** → Region us-west-2 → select your ALB

CLI:
```bash
aws route53 change-resource-record-sets --hosted-zone-id <private-zone-id> --change-batch '{
  "Changes": [{
    "Action": "UPSERT",
    "ResourceRecordSet": {
      "Name": "hyperpod.internal.company.com",
      "Type": "A",
      "AliasTarget": {
        "HostedZoneId": "Z1H1FL5HABSF5",
        "DNSName": "<alb-dns-name>",
        "EvaluateTargetHealth": true
      }
    }
  }]
}'
```
> `Z1H1FL5HABSF5` is the **fixed HostedZoneId for ALBs in us-west-2** (shared by all ALBs in us-west-2;
> the value is published in the AWS documentation). If unsure, check the ALB's `CanonicalHostedZoneId` with `aws elbv2 describe-load-balancers`.
> The outer `--hosted-zone-id` is your **private hosted zone** ID — don't mix up the two.

---

## 5. Export the Private CA Root Certificate + Certificate Chain (PEM)

What the browser needs to trust is the **internal CA's root certificate**, not the leaf certificate on the ALB. Export the root CA from ACM Private CA:

Console: AWS Private CA → select your CA → **CA certificate** tab → copy / download the certificate PEM.

CLI:
```bash
# Export the Private CA's CA certificate (root certificate)
aws acm-pca get-certificate-authority-certificate \
  --certificate-authority-arn <PCA-ARN> --region us-west-2 \
  --output text > internal-root-ca.pem
```
Save it as `internal-root-ca.pem`; in the next step you install it into each machine's trust store.

> **Certificate chain completeness (common pitfall)**: The certificate chain on the ALB must include the intermediate CA (leaf → intermediate → root); otherwise,
> even with the root CA installed, the browser cannot validate the chain. When issuing with Private CA and deploying through ACM, the chain is usually complete.

---

## 6. Install the Trusted Root Certificate on Windows

Install the root CA (`internal-root-ca.pem`/`.crt` from step 6) into
**Trusted Root Certification Authorities → Local Computer**.

Method A (GUI):
1. `Win + R` → `certlm.msc` (Local Computer certificates; requires administrator)
2. Trusted Root Certification Authorities → Certificates → right-click → All Tasks → Import
3. Select the root CA file, and confirm the certificate store is "Trusted Root Certification Authorities"

Method B (administrator PowerShell):
```powershell
Import-Certificate -FilePath "C:\path\internal-root-ca.crt" -CertStoreLocation Cert:\LocalMachine\Root
```
(CMD equivalent: `certutil -addstore -f "Root" "C:\path\internal-root-ca.crt"`)

After installing, **fully close and reopen the browser** (Chrome/Edge use the Windows system trust store; the process must fully exit and restart).

Verify:
```powershell
Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Subject -like "*<your-ca-name>*" }
```
> Firefox is the exception: it has its own trust store, so you need to import the certificate separately in Firefox settings.

---

## 7. Trust the Root Certificate on Mac

Install the root CA into the system keychain and set it to "Always Trust":

GUI:
1. Double-click `internal-root-ca.pem` → Keychain Access → add it to the **System** keychain
2. Find the CA certificate → double-click it → expand "Trust" → **When using this certificate: Always Trust**

Command line:
```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain internal-root-ca.pem
```
Restart the browser after installing.

---

## 9. Verify in the Browser

1. Go to `https://hyperpod.internal.company.com` → the address bar should show a **padlock / Secure** (no longer Not Secure)
2. A secure context is established → `crypto.subtle` is available → the PKCE `digest` error goes away
3. If not signed in, you are redirected by the ALB to **Cognito Hosted UI → IdC** to sign in
4. After sign-in, the callback `/oauth2/idpresponse` takes you into the platform

**If it still shows Not Secure, click the warning in the address bar and use the error code to pinpoint the cause:**
- `ERR_CERT_AUTHORITY_INVALID` → the root CA was installed in the wrong store / the leaf certificate was installed instead of the root CA
- `ERR_CERT_COMMON_NAME_INVALID` → the certificate SAN does not include the internal domain (go back to step 3 and reissue)
- Certificate chain errors → the ALB certificate chain is missing the intermediate CA (go back to step 6 and check chain completeness)

**Organization-wide rollout**: Installing the root CA manually is only suitable for debugging. For all users, IT should distribute the internal root CA
to employee machines' trust stores via **AD Group Policy (GPO) / MDM / Jamf**.
