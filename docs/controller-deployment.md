# platform-controller Deployment Guide

**English** | [简体中文](controller-deployment.zh-CN.md)

A Go controller-runtime projection controller: it watches three kinds of CRs in the business cluster across clusters
(training HyperPodPyTorchJob / inference InferenceEndpointConfig / dev instance Workspace) +
Kueue Workload + Pod, and projects the derived status one-way into DynamoDB. **It replaces the original Python platform-worker.**

## Architecture: spanning two clusters

```
┌─ Platform cluster (cluster X) ─┐        ┌─ Business cluster (cluster Y, hyperpod) ─┐
│  platform-controller Pod       │        │                                          │
│   - leader election lease ─────┼── in-cluster SA of this cluster                   │
│   - watch CR/Workload/Pod ─────┼───────▶│  Read-only (access entry + RBAC)         │
│   - write DynamoDB             │        │                                          │
└────────────────────────────────┘        └──────────────────────────────────────────┘
```

- **Business cluster (watch target)**: `BUSINESS_EKS_CLUSTER_NAME` → the entrypoint runs `aws eks update-kubeconfig`
  to generate a kubeconfig (`BUSINESS_KUBECONFIG` points to it), whose exec section runs `aws eks get-token` to get a token
  (client-go refreshes it automatically, so you do not hit the 15-minute 401).
- **Platform cluster (where the controller runs)**: the leader election lease lives here (nothing is placed in the business cluster),
  using the Pod's own ServiceAccount (in-cluster, `PLATFORM_KUBECONFIG` left empty).

> **The Pod deployment only needs the business cluster name** (`BUSINESS_EKS_CLUSTER_NAME`): `BUSINESS_KUBECONFIG` is generated automatically by the entrypoint,
> and `PLATFORM_KUBECONFIG` is left empty to use in-cluster config. You only need to specify paths for the two `*_KUBECONFIG` variables manually during local development.

## Prerequisite: IAM identity permissions

The controller's runtime identity (Pod Identity or IRSA) needs:

| Permission | Purpose |
|---|---|
| `eks:DescribeCluster` (business cluster) | The entrypoint's `update-kubeconfig` reads the endpoint + CA |
| Business cluster **access entry** | The API server recognizes this IAM identity and maps it to an RBAC group |
| DynamoDB `GetItem`/`UpdateItem` (target table) | Projection writes to DDB |

## Deployment steps

### 1. Build + push the image

```bash
cd services/platform-controller
docker build -t <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/<PROJECT>-platform-controller:<TAG> .
aws ecr get-login-password --region <REGION> | docker login --username AWS --password-stdin <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com
docker push <ACCOUNT>.dkr.ecr.<REGION>.amazonaws.com/<PROJECT>-platform-controller:<TAG>
```

### 2. Business cluster authorization (RBAC + access entry)

```bash
# access entry: map the IAM role to the K8s group "platform-controller"
aws eks create-access-entry --cluster-name <BUSINESS_EKS_CLUSTER> \
  --principal-arn arn:aws:iam::<ACCOUNT>:role/<PROJECT>-platform-controller \
  --kubernetes-groups platform-controller --type STANDARD

# Read-only RBAC (get/list/watch on CR/Workload/Pod)
kubectl --context <business-cluster> apply -f deploy/business-cluster-rbac.yaml
```

### 3. Platform cluster deployment

Edit `deploy/deployment.yaml` to replace the placeholders (`<ACCOUNT>` `<REGION>` `<PROJECT>` `<TAG>`
`<DDB_TABLE>` `<BUSINESS_EKS_CLUSTER>`), then:

```bash
kubectl --context <platform-cluster> apply -f deploy/deployment.yaml
```

This step creates the ServiceAccount + the leader election Role/RoleBinding (leases permission in this cluster) + the Deployment.

### 4. First rollout: validate with DRY_RUN first, then write for real

⚠️ **Single-writer constraint during migration**: The same DDB table must not be written for real by both the Python worker and the Go controller at the same time.

```
1. Confirm the Python platform-worker is stopped (scale it to 0 or delete the Deployment)
2. Deploy first with DRY_RUN=true in deployment.yaml → check the logs to confirm the derivation is correct (no database writes)
   kubectl -n platform-system logs -f deploy/platform-controller
   # Log lines look like: [DRY_RUN] UpsertStatus key=.../inference#... ks=Admitted phase=...
3. Once validated → change to DRY_RUN=false and run kubectl apply → Go becomes the single writer
```

## Configuration (environment variables)

| Variable | Required | Default | Description |
|---|---|---|---|
| `AWS_REGION` | | us-west-2 | |
| `DDB_TABLE` | ✅ | | **Full name** of the ResourceIndex table (not a prefix) |
| `BUSINESS_EKS_CLUSTER_NAME` | ✅ | | Business cluster name (the entrypoint generates the kubeconfig) |
| `DRY_RUN` | | false | true = log only, no database writes (for initial validation) |
| `ENABLE_LEADER_ELECTION` | | true | Used for multi-replica hot standby |
| `LEADER_ELECTION_NAMESPACE` | | platform-system | Namespace that holds the lease (this cluster) |
| `PLATFORM_KUBECONFIG` | | (empty = in-cluster) | Platform cluster kubeconfig; leave empty inside the Pod |
| `BUSINESS_KUBECONFIG` | | (set by entrypoint) | Path to the business cluster kubeconfig; generated automatically by the entrypoint inside the Pod |

## Health checks

- `:8081/healthz` (liveness), `:8081/readyz` (readiness)
- `:8080/metrics` (Prometheus)

## Resource usage (measured, for reference)

| | Python worker | Go controller |
|---|---|---|
| requests | cpu 200m / mem 512Mi | **cpu 50m / mem 64Mi** |
| limits | cpu 1 / mem 1Gi | **cpu 500m / mem 256Mi** |
| Measured RSS | — | ~35Mi (including cache) |
| Image | ~260MB (python+venv) | ~depends on debian-slim + binary; the binary itself is 46MB |

## Operations notes

- **A single instance is enough**; for hot standby you can add replicas, and leader election ensures only 1 does the work.
- **Restarts are harmless**: reconciliation is level-based, so after a restart it reads everything back from the cache and recomputes. The deletion index (in memory) is lost on restart,
  and the 10h resync acts as the safety net (deletions are primarily finalized by the frontend DELETE API).
- **Rollback**: When switching back to the Python worker, stop the Go controller first (to avoid dual writes), then start the worker.
