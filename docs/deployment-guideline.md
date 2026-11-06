# HyperPod Team Portal · Deployment Guide

**English** | [简体中文](deployment-guideline.zh-CN.md)

Deploy the entire platform from scratch in a single AWS Region.

## Prerequisites (deployment host)

On the machine that runs the deployment scripts (macOS or Linux; we recommend that, after Step 0 of this guide, you follow [ec2-deployer-setup.md](ec2-deployer-setup.md) and run the deployment from an EC2 instance), install the following first:

| Tool | Version requirement |
|---|---|
| **aws cli** | v2 |
| **kubectl** | ≥ 1.30 (should not lag too far behind the cluster version 1.35) |
| **helm** | v3 |
| **docker** | Running (on Apple silicon Macs it must support `--platform linux/amd64`); node/pnpm are **not** required on the host, because the frontend is built inside a container |
| **AWS CDK** | v2 (`aws-cdk-lib==2.150.0`, global `cdk` ≥ 2.150) |
| **python3** | 3.11 |
| **git** | Any |


## EKS cluster roles

- **Business cluster** = where HyperPod, FSx, and dev instances live (created with Custom setup in the console).
- **Platform cluster** = where the frontend, backend, and worker run (created by CDK). Both clusters are in the same VPC.

## What each script does

| Script | Phase | Default behavior |
|---|---|---|
| `deploy/cluster-prereq.sh`  | Business cluster preparation (after filling in cdk.json, before CDK) | verify→ebs→ssm→pd→spaces→externaldns→logging→template→fsxadmin→lws |
| `deploy/deploy-platform.sh` | Platform deployment (starting with CDK)     | init→build→apply (the cdk step must be specified explicitly) |
| `deploy/cognito-callback.sh`| Wrap-up                  | Backfill the Cognito callback |

---

## End-to-end overview

```
Manual·console   Create VPC/subnets/SG + Custom setup for EKS+HyperPod + FSx (Lustre 2.15, multiple allowed)
                                  │
Manual           Fill in infrastructure/cdk.json
                                  │
Script ①         cluster-prereq.sh   (business cluster add-ons/IAM/template/fsx-admin/directSSH; reads cdk.json automatically)
                                  │
Script ②         deploy-platform.sh  (cdk → init → build → apply)
                                  │
Manual·wrap-up   cognito-callback.sh  +  cross-cluster-sg.sh to allow 8888/443  + associate Identity Center groups and verify sign-in
```

---

## Step 0 · Manual console steps (not covered by the scripts)

1. **Optional (skip this if you create a new VPC together with the HyperPod cluster): VPC/subnets/SG**: The VPC CIDR must not overlap with the EKS Service CIDR `172.20.0.0/16` (for example, use `10.90.0.0/16`). Subnets: 2 public + 2 private-EKS + 1 or more private-HyperPod. **The HyperPod node subnet must be in the same AZ as FSx**. The FSx security group must allow inbound **988 + 1018-1023**.
2. **Required (the VPC, HyperPod cluster, and FSx can be created together): Create the HyperPod cluster**: Amazon SageMaker AI HyperPod clusters console → Orchestrated by Amazon EKS → Custom setup → Create HyperPod cluster → enter a Name → under Networking, choose the VPC and related settings (recommended: Create a new VPC, enter a CIDR range, select 3 AZs, and choose Create a new security group) → for Orchestration, choose "Create a new EKS cluster" → set Kubernetes version to 1.35 → under Operators, in addition to the required defaults, also select HyperPod patching and HyperPod training operator → under Instance Group, choose Add group (you can start with a CPU instance group: instance type m5.4xlarge or larger, count 2 or more) → under Permissions, choose Create a new IAM role → keep the default FSx file system selection, or adjust Throughput per unit of storage, Storage capacity, and so on as needed (if an FSx file system already exists in the same VPC, choose None) → keep all other defaults → **Submit**. This creates EKS + HyperPod and automatically sets up the basic add-ons, IAM role, and Pod Identity. However, it **does not include spaces / ebs-csi** (the scripts install these two add-ons later).
3. **Optional: Make the business EKS cluster private**: In the EKS console, find the EKS cluster created by the HyperPod cluster and make it private: Networking → Manage → Endpoint access → Private → Save changes
4. **Optional (skip this if it was created along with the HyperPod cluster): Create FSx for Lustre**: FSx console → Persistent SSD, ≥1.2TiB, choose the same VPC as EKS and a subnet in the same AZ, and make the security group allow the EKS security group to reach ports 988 + 1018-1023. **The Lustre version must be 2.15** (2.12 does not support project quotas, so directory quotas fail silently: `lfs setquota` appears to succeed but `lfs quota` returns `Operation not supported`; the console defaults to 2.12, so expand the advanced settings and change it explicitly). **Write down the File system ID (`fs-xxxx`)**. You can create multiple file systems (the platform supports multiple FSx file systems); write down the ID of each one.
5. **Required: Priority classes (cluster policy)**: The source of truth for priority classes is the SageMaker HyperPod task governance **cluster policy** (`ClusterSchedulerConfig`). The platform no longer creates its own Kueue WorkloadPriorityClass objects (`deploy/k8s/workload-priority-classes.yaml` is deprecated and cluster-init no longer applies it). All six platform task types (dev/train/inference/dynamo/llmd/rayjob) default to the `common-priority` class, but the cluster policy that ships with a HyperPod cluster **does not include `common`**, so you must add it manually. The WPC name referenced by a CR = the class name in the policy + the `-priority` suffix (for example, entering `common` in the policy produces the WPC `common-priority`).

   - **New installation**: SageMaker AI console → HyperPod Clusters → select the cluster → **Policies** tab → edit **Cluster policy** → **set Task prioritization to `Task ranking`** → under **Priority classes**, choose **Add**, set Name to `common` and Weight to `80` (0-100; higher means higher priority) → save. Once it takes effect, SageMaker automatically creates the managed `common-priority` WPC in the cluster.

   - **Upgrade installation (upgrading from an older version)**: Older versions used `deploy/k8s/workload-priority-classes.yaml` to create a set of **self-managed** WorkloadPriorityClass objects in the business cluster (`common-priority`/`high-priority`/`extremely-high-priority`/`low-priority`/`extremely-low-priority`, and so on). When upgrading, you **must delete all self-managed classes first**; otherwise, they conflict when the cluster policy generates WPCs with the same names (the error is `already exists and is not managed by SageMaker`, and the policy becomes `UpdateFailed`). Self-managed classes do not have the `sagemaker.amazonaws.com/sagemaker-managed-queue` label, while the official managed classes do, so use a negative label selector to target them precisely:

     ```bash
     # ① First list the self-managed (non-SageMaker-managed) classes to be deleted, and visually confirm they are all self-managed leftovers
     kubectl --context "$BUSINESS_CTX" get workloadpriorityclass \
       -l '!sagemaker.amazonaws.com/sagemaker-managed-queue'

     # ② After confirming, delete them (only non-managed classes are deleted; official managed classes are unaffected)
     kubectl --context "$BUSINESS_CTX" delete workloadpriorityclass \
       -l '!sagemaker.amazonaws.com/sagemaker-managed-queue'
     ```

     After deleting them, create the `common` class on the platform UI's **Priority Class page** (enter the bare name `common` as the Name, with a weight of 0-100), or use the console cluster policy method described under "New installation" above. Creating a class in the UI actually calls SageMaker `CreateClusterSchedulerConfig`, and task governance takes over generating the managed WPC.

   > ⚠️ The priority of tasks that are already running or queued is a **numeric snapshot taken at creation time**, so deleting self-managed classes does not affect their execution. However, before deleting the classes, confirm that no critical task that will be recreated (restart/auto-resume) depends on them (after recreation, the class cannot be found → Kueue falls back to priority=0).
   >
   > **Permissions**: Managing the cluster policy requires `sagemaker:{Describe,List}Cluster`, `sagemaker:ListClusterSchedulerConfigs`, `sagemaker:{Describe,Create,Update,Delete}ClusterSchedulerConfig`, plus `eks:DescribeCluster` + `eks:AccessKubernetesApi`. Class creation in the UI is initiated by the platform-api backend role, which must include the `*ClusterSchedulerConfig` permissions above (see the backend role policy in CDK).

---

## Step 1 · Fill in cdk.json (manual)

Edit the `context` in `infrastructure/cdk.json`:

| key | What to enter |
|---|---|
| `projectName` | Project prefix (resource name prefix, such as `hpd-plat`) |
| `account` / `region` | Account / Region |
| `vpcId` / `privateSubnetIds` | The VPC created in Step 0 of this guide + private subnets with a NAT gateway (≥2) |
| `platformClusterSuffix` | Suffix of the platform EKS cluster name; cluster name = `{projectName}-{platformClusterSuffix}` (default `deployplat`) |
| `platformK8sVersion` | Kubernetes version of the platform EKS cluster (such as `1.35`) |
| `businessClusterName` / `hyperpodClusterName` | Business cluster EKS name / HyperPod name |
| `hyperpodClusterLogGroupName` | Full name of the CloudWatch log group for HyperPod cluster container logs, `/aws/sagemaker/Clusters/<cluster>/<id>`; used by the backend's fast log path. If left empty, the backend falls back to a reverse lookup |
| `logArchiveMode` | Mode for backing up logs to S3: `cost` = Firehose writes the raw gz files, saving storage (requires Glue ETL conversion to Parquet for convenient querying); `query` = decompressed and written as plain text, directly queryable with Athena, but larger S3 footprint; empty = the log backup stack is not deployed |
| `platformFsxFilesystems` | List of FSx file systems connected to the platform, comma-separated `fs-id` values (such as `fs-0aaa,fs-0bbb`). The fs-id is used directly as the mount point subdirectory `/fsx-mnt/<fs-id>` in the fsx-admin pod (inherently path-safe); the display name in the frontend quota/monitoring dropdowns comes from the AWS `Tags[Name]` (shown as `name (fs-id)`). **Every file system must be Lustre 2.15** (see Step 0 §4). If left empty, the quota/monitoring pages have no file systems to choose from. (The legacy format `fs-id:alias` is still accepted; the alias segment is ignored.) |
| `directSshDomain` | **Private** domain name used for native SSH to dev instances (directSSH), such as `dev-ssh.hyperpod.internal` (an internal domain name you choose yourself; no purchase needed). Only when this is set does `cluster-prereq.sh` create the full directSSH stack (Route 53 private hosted zone + external-dns role/add-on + spaces add-on with directSSH enabled and SSM disabled); dev instances then get a fixed DNS name that stays the same across stop/start, plus port 22222. If left empty, connections fall back to SSM |
| `ampWorkspaceId` | AMP workspace ID for the observability add-on; you can open the Amazon Prometheus console and find the Workspace ID of the corresponding workspace |
| `idcIdentityStoreId` / `idcRegion` | Fill these in when integrating with Identity Center. The Store ID is in the IAM Identity Center console under Settings -> Identity source -> Identity Store ID on the right |
| `idcAssumeRoleArn` | **Only for cross-account setups**: When IdC is in the organization management account and the application is in another account, enter the ARN of a read-only role in the management account (the backend first calls AssumeRole and then queries IdC). Leave empty for same-account setups. For the role creation steps, see [`identity-center-cognito-configuration.md`](identity-center-cognito-configuration.md) §4. Note that in this case `idcIdentityStoreId`/`idcRegion` must still be set to the values of the identity store in the management account |
| `platformS3Buckets` | S3 buckets to mount, format `bucket[:region[:friendly-name]]`, comma-separated for multiple |
| `albDomainName` | Domain name for accessing the platform (fill in only if you have one) |
| `albCertificateArn` | ARN of the HTTPS certificate for the platform ALB (ACM, **must be in the same Region as the ALB**), in the form `arn:aws:acm:<region>:<account>:certificate/xxxx`. **Empty = HTTP:80 only**; set = HTTPS:443 enabled (80 automatically redirects to 443). To create a private certificate for an internal domain, see [`internal-domain-deployment.md`](internal-domain-deployment.md): §2 creates a Private CA → §3 uses that CA to issue a certificate into ACM (enter the ACM certificate ARN produced in §3 here, not the CA ARN from §2) |
| `platformNamespace` | Kubernetes namespace for the platform frontend and backend (default `platform-system`) |
| `platformEndpointPublicAccess` | Whether the platform cluster API endpoint is publicly accessible. `true` = local kubectl can connect directly (during integration testing); `false`/omitted = private-only (production; operations go through an EC2 instance in the VPC or a VPN). To switch to private, change this to false and run cdk deploy again |
| `clusterWorkspaceAdminGroup` | The default `cluster-workspace-admin` is fine; change it only if the business cluster spaces operator's `CLUSTER_ADMIN_GROUP` is not the default (the two must match) |
| `bootstrapAdmins` | Initial platform admin usernames, comma-separated for multiple |

After filling it in, install the CDK Python dependencies + bootstrap (first time for a new account):

```bash
cd infrastructure && python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cdk bootstrap && cd ..   # first time for a new account and Region; skip if already bootstrapped
```

---

## Step 2 · Business cluster preparation (script ①)

Parameters are read automatically from cdk.json (region/account/businessClusterName/platformFsxFilesystems/directSshDomain), so just run:
 
```bash
chmod +x deploy/*.sh
./deploy/cluster-prereq.sh
```

The script runs, in order: `verify` validation → `ebs` installs EBS CSI + role → `ssm` creates the SSM role → `pd` enables Prefix Delegation + installs maxpods-patcher (raises maxPods; **must run before spaces**) → `spaces` installs the spaces add-on → `externaldns` creates the Route 53 zone + role + external-dns add-on for directSSH → `logging` enables container logs → `template` enables allowCustomImages → `fsxadmin` starts the fsx-admin pod (mounting every file system in `platformFsxFilesystems`) → `lws` installs LeaderWorkerSet (llm-d multi-node inference).

> ⚠️ Running `pd` before `spaces` is mandatory: by default, a HyperPod node with a single ENI supports only ~29 pods. If maxPods is not raised first, pods for spaces and other add-ons cannot be scheduled → the add-on becomes `DEGRADED`.

> Both `spaces` and `externaldns` depend on `directSshDomain` in cdk.json: if it is set, the spaces add-on enables `directSSH` (port 22222) and disables remoteAccess (SSM), and `externaldns` creates the private hosted zone + IAM role + external-dns add-on, which syncs the SSH Services automatically created by spaces to fixed DNS names. If it is empty, spaces uses remoteAccess (SSM) and `externaldns` is skipped automatically. Both the zone and the role are created by the script itself (**not by CDK**): the script runs before `cdk deploy`, the add-on depends on the role, and the role policy depends on the zone ARN, so all three must exist before CDK. SSH to dev instances also requires `deploy/cross-cluster-sg.sh` to open port 22222 on the node security group (see Step 4 §2).

> `fsxadmin` uses `platformFsxFilesystems` in cdk.json to start **one** fsx-admin pod that mounts **multiple file systems**, each with its own PV/PVC pair (`fsx-admin-pv-<fs-id>`), mounted at `/fsx-mnt/<fs-id>`. The script describes the DNS name and MountName automatically, so you do not need to enter them. If you change the file system list, just rerun `./deploy/cluster-prereq.sh fsxadmin` (the Deployment is deleted and recreated, so no stale mounts remain for removed file systems).

> There is a 1-2 minute delay between installing spaces and the template being seeded. If the `template` step reports "cannot get workspacetemplate", wait a moment and rerun it on its own: `./deploy/cluster-prereq.sh template`.

> The `logging` step sets `metricsProvider.logging.enabled` to `true` in the observability **add-on's configurationValues** (`aws eks update-addon`; it reads the existing config, merges, and writes it back, without touching AMP/Grafana/metrics or other settings). The operator then automatically starts the `fluent-bit` DaemonSet, which pushes container logs (training jobs/dev instances) to the CloudWatch log group `/aws/sagemaker/Clusters/<cluster>/<id>`. **Without this step, training logs do not reach CloudWatch**. Permissions come from the add-on's own service account (which already includes `logs:*` on `/aws/sagemaker/Clusters/*`), so no additional IAM is needed. After about 1 minute, verify with `kubectl get ds -n hyperpod-observability | grep fluent-bit`.

You can run specific steps on their own: `./deploy/cluster-prereq.sh pd` (enable PD + maxpods) / `./deploy/cluster-prereq.sh ebs ssm spaces` / `./deploy/cluster-prereq.sh externaldns` / `./deploy/cluster-prereq.sh fsxadmin` / `./deploy/cluster-prereq.sh logging` / `./deploy/cluster-prereq.sh verify`.

---

## Step 3 · Platform deployment (script ②)

```bash
# Fully automated (includes cdk, ⚠️ automatically approves IAM changes)
./deploy/deploy-platform.sh cdk init build apply

# Or: run cdk deploy manually first to review the diff, then run the default three steps
cd infrastructure && cdk deploy <projectName>-platform-stack && cd ..
./deploy/deploy-platform.sh        # = init build apply

# Specify the image tag
TAG=v2 ./deploy/deploy-platform.sh

# Re-run apply only (after changing manifests)
./deploy/deploy-platform.sh apply
```

Steps: `cdk` creates the platform cluster and resources → `init` sets up kubeconfig + access entry + ALB + business cluster RBAC (platform-api-manager) → `build` pushes 3 images → `apply` renders and deploys the manifests. `init/build/apply` read parameters automatically from cdk.json + CDK Outputs, so you do not need to copy ARNs by hand. (Priority classes are no longer created by init; see item 5 of Step 0.)

---

## Step 4 · Wrap-up (scripts & manual)

```bash
# 1. Backfill the Cognito callback (default localhost:8080, for integration testing over an SSM tunnel)
./deploy/cognito-callback.sh 
#  Production domain: CALLBACK_URL=https://platform.example.com/auth/callback ./deploy/cognito-callback.sh

# 2. Open cross-cluster security group rules (without this, monitoring/dev instances are unavailable → the backend cannot reach dev instance port 8888 → browser 504)
#    The script automatically looks up DST_SG (HyperPod cluster SG = dev instance pod SG) + SRC_SG (platform node SG) and allows 8888/443
#    When directSshDomain is set in cdk.json, it additionally allows 22222 from all VPC CIDRs (including secondary CIDRs);
#    otherwise, SSH to dev instances from machines inside the VPC times out at the TCP level
./deploy/cross-cluster-sg.sh           # look up automatically + allow
./deploy/cross-cluster-sg.sh verify    # only look up and print the SGs, no changes
```

- **Note · Inference services (single-node / multi-node) require manually allowing ALB → pod traffic**: Add an inbound rule to the EKS **Additional security groups**, with the source set to the ALB's **shared backend SG** `k8s-traffic-<cluster>-<hash>` and port 30000 (multi-node inference gateway).
  Reason: With HyperPod + Prefix Delegation, the AWS Load Balancer Controller (LBC) cannot resolve the pod ENI, so it cannot add this rule automatically. Without it, the ALB returns 504 (the target is registered but health checks time out).

> Optional: Verify connectivity after opening the rules (you can also verify later on the platform) (start a dev instance and test from the backend pod; milliseconds = reachable / 10s timeout = not allowed):
> ```bash
> kubectl --context <platform-ctx> -n platform-system exec deploy/platform-api -- \
>   curl -s -m 10 -o /dev/null -w "%{http_code} %{time_total}s\n" http://<dev-instance-pod-ip>:8888/
> ```

3. (Optional) Add a GPU instance group to the HyperPod cluster. It reuses the LifeCycleConfig/ExecutionRole/SG of an existing instance group. **First fill in at the top of the script**: `NEW_IG_NAME` / `INSTANCE_TYPE` / `INSTANCE_COUNT` / `SUBNET_ID` / `SOURCE_IG_NAME` (the group to inherit from).

   ```bash
   ./deploy/create_new_instance_group.sh
   ```

4. Configure Identity Center + Cognito; see [identity-center-cognito-configuration.md](identity-center-cognito-configuration.md)

5. Configure an internal domain name for the platform; see [internal-domain-deployment.md](internal-domain-deployment.md)

---

## FAQ

| Symptom | Resolution |
|---|---|
| Opening a dev instance returns `504 Gateway Timeout` (CloudFront) | The backend cannot reach port 8888 of the dev instance pod → the cross-cluster SG rules are not set correctly. Follow Step 4 §2 to allow **DST_SG=HyperPod node SG / SRC_SG=platform node SG**. The backend logs will show `dev_instance.proxy.upstream_err`. Note: do not set the source SG to the ALB/k8s-traffic SG (when ENABLE_POD_ENI=false, pod egress goes through the node) |
| Code Editor shows `WebSocket 1006` / blank page | code-server exposes the pod's private IP, which is hard to fix fully over an SSM tunnel; for integration testing, use VS Code Remote-SSH |
| New pods fail to start with `too many pods` / add-on `DEGRADED` | Node maxPods has not been raised (default ~29). Run `./deploy/cluster-prereq.sh pd` to enable PD + install maxpods-patcher (already included in the normal default flow, before spaces) |
