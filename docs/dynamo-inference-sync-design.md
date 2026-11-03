# Dynamo Multi-node Inference Task Status Sync Design (platform-controller)

**English** | [简体中文](dynamo-inference-sync-design.zh-CN.md)

> Date: 2026-07-12
> Scope: add a new reconciler to `services/platform-controller` (Go, controller-runtime) that
> watches NVIDIA Dynamo's `DynamoGraphDeployment` + the associated Kueue `Workload`s and
> **correctly syncs task status into the DynamoDB `ResourceIndex`**.
> **This design covers data sync (writing to DDB) only.** The read API, response builder, router, task list, task creation,
> queue page display, etc. are implemented separately by the Dynamo task module and are out of scope here.
> Basis: the official Dynamo CRD manifest + real CRs + hands-on testing on the real cluster `eks-hypd-demo` (ns `hyperpod-ns-demo`).

---

## 0. Background and key observed facts

HyperPod single-node inference goes through the SageMaker inference operator (`InferenceEndpointConfig`). **Multi-node inference uses the NVIDIA Dynamo operator instead**: users submit a `DynamoGraphDeployment` (DGD, `nvidia.com/v1beta1`). Topology observed on the cluster (`grove.install=true` / `kai-scheduler.install=false`):

```
DynamoGraphDeployment            (nvidia.com/v1beta1, status.state)
  └─ PodCliqueSet (grove.io)
       └─ PodCliqueScalingGroup  (multi-node worker component)
            └─ PodClique         (one each for leader / worker)
                 └─ Pod          (owner of ↓)
                      └─ Kueue Workload  pod-<podname>-<hash>  (owner = Pod)
  └─ PodGang (scheduler.grove.io) (gang scheduling unit)
```

Key facts (all verified on a real cluster):
1. **Dynamo uses Kueue for scheduling**: the user writes the Kueue labels in the DGD `spec.labels` (`kueue.x-k8s.io/queue-name`, optionally `priority-class`), and the operator propagates them to all child resources (Pods). Grove handles gang orchestration; Kueue handles admission.
2. **Each Pod gets its own Kueue Workload** (owner=Pod, `podSets=main count=1`), so one DGD has multiple Workloads. It is **not** 1 CR ≈ 1 Workload.
3. **The Workload's own labels contain only `kueue.x-k8s.io/job-uid`** (= owner pod uid); the DGD name is **not propagated to the Workload**. Finding the DGD from a Workload must go through the owner Pod.
4. **Pods carry the label `nvidia.com/dynamo-graph-deployment-name=<dgd>`**, so all Pods of a DGD can be listed in one call (observed: exactly 3 matches).
5. DGD `status.state` has 4 states: `initializing / pending / successful / failed`; `status.conditions[type=Ready]`; `status.components{}` (component-level, not pod-level).
6. **Partial-admission deadlock**: if even one Workload in the gang cannot be admitted (insufficient quota), the PodGang stays `Pending` and the DGD stays `pending`, while the already-admitted Pods hold resources idly. The admission status of a single Workload **does not represent** the task status.

---

## 1. Goals and non-goals

**Goal**: add a dynamo reconciler that correctly syncs the following fields into the `metadata` of `ResourceIndex`:
- `phase` — faithfully reflects DGD `status.state`
- `kueue_status` — a single six-state value aggregated across multiple Workloads (taking the "least advanced")
- `status_detail` — the raw DGD `status` (state/components/conditions as-is, symmetric with training / inference / dev instance)
- `active_ws` — whether the task still holds resources (tied to the sparse GSI)

**Non-goals (not in this change)**:
- Any read API / response builder / router / task list / task creation API
- Task Overview page and queue section display
- Computing and persisting the `positionInLocalQueue` queue position (the controller currently has no such capability; left for later implementation as needed)
- Watching Grove resources (PodClique/PCSG/PodGang) (x/y is instead aggregated from Workloads, see §4)

---

## 2. Architecture: a 4th instance of the existing CRReconciler

platform-controller has a generic `CRReconciler` (`internal/controller/reconciler.go`) that is instantiated 3 times in `SetupAll` (`internal/controller/setup.go`) (train / inference / dev). **Add a 4th instance, `dynamo`**, following the existing pattern exactly:

- **Primary watch = DGD**: `For(gvk.DynamoGraph)`. DGD events drive reconcile.
- **Associated watch = Workload**: `Watches(Workload, EnqueueRequestsFromMapFunc(mapping.WorkloadToCR(...)))` — the same shape as the existing inference / dev instance path (owner=Pod, 2 hops). Workload event → owner Pod → read the `dynamo-graph-deployment-name` label → trigger reconcile of the corresponding DGD.

This naturally satisfies the dual-watch requirement ("watch CR + watch workload") without building a new watcher.

Reconcile keeps the existing 5-step loop: read CR (NotFound → soft delete) → resolveIDs → **fetchWorkloads (plural, new)** → derive.Derive → writer.UpsertStatus. Everything in the write layer (`ddb/writer.go`) — partial update + dedup + rv gate + **active_ws / kueue_status bypass** — is type-agnostic and reused as-is.

---

## 3. Workload association: forward lookup (aggregation) and reverse lookup (triggering)

This is the **only structural addition** of this design relative to the existing code. The existing `fetchWorkload` fetches "the latest single Workload", which does not hold for Dynamo's multiple Workloads.

**Reverse lookup (Workload event → DGD, triggers reconcile)** — add a Dynamo branch to `mapping.WorkloadToCR`:
- Workload → owner Pod (`ownerReferences`, 1 level) → read Pod label `nvidia.com/dynamo-graph-deployment-name` = DGD name → enqueue that DGD.
- Same shape as the existing 2-hop mapping; only the Pod label key differs.

**Forward lookup (DGD → all Workloads, for aggregation)** — add `fetchWorkloads` (plural). **Everything is read in memory from the manager cache, with zero extra API calls**: since `Watches(Workload)` already brings these Workloads into the manager cache via an informer, and controller-runtime's client `List` reads from the cache by default, aggregation happens entirely in memory. Steps:
1. cache `List` Pods with `MatchingLabels{nvidia.com/dynamo-graph-deployment-name: <dgd-name>}` → get all Pods of the DGD (observed to be exact, including frontend + every worker) and collect their `uid` set.
2. cache `List` the Workloads in this namespace → filter in memory by `kueue.x-k8s.io/job-uid ∈ uid set` to get all Workloads belonging to the DGD (pod-uid join).
3. Collect all of these Workloads and hand them to the derive layer for aggregation.

> Key point: Workloads themselves **have no DGD label** (observed: only job-uid), so they cannot be filtered in one step; the uid↔DGD ownership must first be established through the Pods. But both steps are in-memory cache reads, with no API round trips.
> Alternative (rejected): list Workloads directly by DGD label in one step — not feasible, since Workloads were observed to have no DGD label.

---

## 4. Status derivation rules (`derive/derive_dynamo.go`, new)

### phase (faithfully reflects the CR)
- Take DGD `status.state` directly (`initializing/pending/successful/failed`), **without normalization**. Fall back to `initializing` if missing (the CRD default).

### kueue_status (aggregated across Workloads, taking the "least advanced")
1. Run the existing `deriveKueueFromWorkload()` on each child Workload to get its individual six-state value.
2. **Aggregate = take the least advanced**: add `aggregateKueue(workloads)`, reusing the existing `kueuePriority` (`Finished>Evicted>PodsReady>Admitted>QuotaReserved`), and pick the one with the **lowest priority (least progress)**. Rule: if any one is `Queued` → the task is `Queued`; otherwise if any is `QuotaReserved` → `QuotaReserved`; only when all are `Admitted` (including PodsReady) is it considered ready.
3. If no Workload can be found at all and the DGD is in the terminal set (see below) → return `Finished`; otherwise return `""` (freeze signal: the write layer keeps the old DDB value, reusing the existing semantics).

> **Key observation (2026-07-13, dynamo-probe successful for 40h)**: Dynamo's Kueue Workloads **only ever have the `QuotaReserved` + `Admitted` conditions and never show `PodsReady`** (this Grove+Kueue pod integration does not enable PodsReady tracking). Therefore:
> - **The kueue_status of a Dynamo task in the "ready" state tops out at `Admitted`** (it never reaches PodsReady); the aggregation logic must not wait for PodsReady as the readiness signal.
> - For Dynamo, the Kueue six states only reflect the "resources allocated / admitted" layer; **whether the service is truly ready to receive traffic is determined by DGD `status.state=successful` / `conditions[Ready]=True`**, not by Kueue. This again confirms that phase and kueue_status are two orthogonal dimensions.
> - All three Workloads (frontend + ldr + wkr) were observed with `QuotaReserved=True, Admitted=True` → aggregation result = `Admitted`. job-uid was observed to exactly equal the owner pod uid (e.g. ldr pod uid `98fe6ca0…` = its workload's job-uid), so the aggregation join key holds.

### status_detail (stores the raw DGD status, symmetric with training / inference / dev instance)
**Store only the DGD's raw `status`** (`state` / `components` / `conditions` / `observedGeneration` as-is), refreshed whenever the CR changes — exactly the same approach as the existing `derive_training`/`derive_inference`/`derive_dev`, which put the raw CR status fragment into `status_detail`. Observed status structure in the successful state (persisted as-is):
```json
{
  "state": "successful",
  "components": {
    "Frontend": {"componentKind":"PodClique","readyReplicas":1,"replicas":1,"updatedReplicas":1,"componentNames":["dynamo-probe-0-frontend"]},
    "worker":   {"componentKind":"PodCliqueScalingGroup","availableReplicas":1,"replicas":1,"updatedReplicas":1,"componentNames":["dynamo-probe-0-worker"]}
  },
  "conditions": [{"type":"Ready","status":"True","reason":"all_resources_are_ready","message":"All resources are ready","lastTransitionTime":"..."}],
  "observedGeneration": 1
}
```

**Do not persist** derived information (admitted x/y, per-Workload details, stuck messages, per-WL queue positions). The read side queries Kueue/Pods in real time when it needs them; none of this goes into DDB. Reason: symmetry with the existing resource types (status_detail only stores the raw CR status), and such details are volatile, so persisting them risks serving stale data.

> Note: `status.components` is **component-level** (worker=PodCliqueScalingGroup shows only 1 gang group, `replicas:1`, not the 3 underlying Pods), and its fields vary with componentKind (PodClique has `readyReplicas`, PCSG only has `availableReplicas`). Therefore **it cannot be used to compute pod-level x/y** — but storing it as-is as the raw status is fine; the read side interprets it.

### Terminal set
- DGD `status.state == failed` is treated as a terminal candidate (see the active_ws decision in §5).
- `successful` is a service state meaning "deployed successfully, running long-term"; it is **not** a terminal state (inference services do not end on their own).

---

## 5. active_ws (whether resources are still held)

Reuse the existing sparse GSI mechanism (the three states `ActiveSet/ActiveRemove/ActiveFreeze` in `writer.go` + the rv bypass).

| DGD situation | active_ws | Reason |
|---|---|---|
| initializing / pending / successful | **Keep** (ActiveSet) | Running or queued; holding or trying to hold resources |
| pending with partial admission stuck | **Keep** | The admitted Pods actually hold resources |
| failed | **⚠️ To be finalized after testing** (see below) | Cannot rely on the aggregated kueue_status alone; must drill down into the actual Pods |
| User stops / deletes the DGD | Remove (ActiveRemove) | MarkDeleted |

**active_ws decision for failed (to be finalized after testing; cannot rely on the aggregated kueue_status alone)**:

The initial design assumed that "when failed, as long as there are active Workloads, the aggregate is naturally an active state, so active_ws is kept automatically with no extra check" — **this inference does not hold**. failed is the most semantically uncertain state in Dynamo:
- The Workloads may already have been cleaned up by the operator (fetchWorkloads finds nothing → aggregation returns freeze/Finished), while the underlying **Pods are in fact still Running/Pending and holding GPUs**;
- Conversely, the Workloads may still exist while the Pods have already exited.

Therefore the resource-holding decision for failed **must drill down into the actual Pods**, following the existing GPU-occupancy logic for **training** — `trainOccupyingActive` + `activeByLivePod` in `derive_training.go` (List the task's Pods, check whether any of them are Running/Pending, and decide ActiveSet/ActiveRemove accordingly). Dynamo should reuse the same idea: when failed, List the DGD's Pods (the same cache list of Pods as in §3); if there are Running/Pending Pods → keep active_ws; if all have exited → kueue_status=Finished + remove active_ws.

**The exact rule will be finalized after observing a real failed DGD** (see §7): the actual combination of DGD.state / Workload / Pod states when failed must be observed before the drill-down criterion can be settled (whether checking the Pod phase is enough, or whether PodClique must be checked). Until it is finalized, the implementation reuses training's `activeByLivePod` pattern as a placeholder.

---

## 6. Files to change / add (all in platform-controller)

| File | Change |
|---|---|
| `internal/gvk/gvk.go` | Add the `DynamoGraph` GVK (`nvidia.com/v1beta1/DynamoGraphDeployment`); add the Pod label constant `nvidia.com/dynamo-graph-deployment-name`; add it to `AllCRs` as needed |
| `internal/controller/setup.go` | Add a row to the spec table: `{gvk.DynamoGraph, "dynamo", "dynamo-controller", false}`; Workload association via `Watches + mapping.WorkloadToCR` (2 hops) |
| `internal/controller/reconciler.go` | Add a Dynamo case to `fetchWorkload` → call the new **`fetchWorkloads` (plural)**; Dynamo uses a cache list of Pods (by DGD label) + a cache list of Workloads → in-memory pod-uid join (zero extra API calls, see §3). The Pod list used for the failed drill-down reuses the same cache list |
| `internal/controller/associate.go` | Add the Dynamo Pod label key (`nvidia.com/dynamo-graph-deployment-name`) |
| `internal/controller/resolveids.go` | Add Dynamo resource_id / workspace_id label resolution (the injected `platform.hyperpod.io/inference-id` and `workspace-id`; skip if missing, consistent with existing behavior) |
| `internal/mapping/mapping.go` | Add a Dynamo Kind → Pod label case to `CRNameLabelFor` |
| `internal/derive/derive.go` | Add a Dynamo case to the `Derive` dispatch |
| `internal/derive/derive_dynamo.go` | **New**: phase / aggregated kueue_status / status_detail / active_ws derivation |
| `internal/derive/kueue.go` | Add `aggregateKueue(workloads)` (takes the least advanced, reusing `kueuePriority`) |
| `deploy/business-cluster-rbac.yaml` | Add `apiGroups:["nvidia.com"] resources:["dynamographdeployments"] verbs:[get,list,watch]` to the ClusterRole (Workload/Pod permissions already exist) |

**Unchanged**: `ddb/writer.go` (partial update / dedup / rv gate / active_ws bypass are all type-agnostic); the table schema (defined on the platform-api side in `tables.py`; the controller just writes fields by convention — a `RESOURCE_TYPE_DYNAMO` constant + a `VALID_TYPES` entry need to be added to platform-api's `tables.py`; this is a read-side coordination item and is only recorded as a dependency here).

> **Cross-repo dependency note**: the controller can simply write the string convention `resource_type = "dynamo"` (the controller does not validate VALID_TYPES; that is the platform-api read side's job). But so that the read side does not reject it, `dynamo` must be added to platform-api `tables.py::VALID_TYPES`. This is a coordination item, not part of this code delivery.

---

## 7. Open items / to be verified

1. ~~**Label injection for resolveIDs**~~ **✅ Resolved (2026-07-14, verified on the platform creation path with `test-multi-01-yr1h08ude5`)**: DGDs created from the platform frontend already have the full set injected in `metadata.labels` (exactly where the existing resolveIDs reads, `cr.GetLabels()`):
   - `platform.hyperpod.io/dynamo-id` = resource_id (**note that the key is `dynamo-id`, not `inference-id` — confirming the separate type `dynamo`**)
   - `platform.hyperpod.io/workspace-id` = workspace_id
   - `platform.hyperpod.io/creator-id` = creator (used when creating the stub)
   - Additionally `platform.hyperpod.io/framework` (sglang) and `kueue.x-k8s.io/priority-class` (observed: `common-priority`, consistent with the existing inference path)
   → resolveIDs only needs `resourceIDLabelFor("DynamoGraphDeployment") = "platform.hyperpod.io/dynamo-id"`; workspace-id reuses the existing `labelWorkspaceID`.
2. **Actual failed behavior (the only remaining blocker; blocks finalizing §5)**: only `pending`/`successful` were observed in testing; **no `failed` instance was captured**. §5 explicitly states that the active_ws decision cannot rely on the aggregated kueue_status alone and must drill down into the actual Pods (following training's `activeByLivePod`). **A failed DGD must be created (wrong image / wrong command) to observe on site the actual combination of DGD.state / Workload / Pod states when failed** before the drill-down criterion can be finalized (whether checking the Pod phase is enough, or whether PodClique / operator Pod restarts must be considered). Until it is finalized, the implementation uses training's GPU-occupancy pattern as a placeholder.
3. ~~**resource_id value**~~ **✅ Resolved**: use the value of the `platform.hyperpod.io/dynamo-id` label (see item 1), consistent with the existing label path; no uid/name fallback needed.
4. **Whether the kueue_status aggregation includes Frontend**: the aggregation currently includes all Workloads of the DGD (frontend + workers). Frontend is single-node and is usually ready first; testing is needed to determine whether, in some scenario, the Frontend queuing on its own would unreasonably drag the whole task to Queued. To aggregate over workers only, fetchWorkloads can filter by `nvidia.com/dynamo-component=worker`. By default all are included.

---

## 8. Verification

- Unit tests: `derive_dynamo_test.go` covers the aggregation rules (all admitted, partial admission, all queued, includes Finished), the GPU-occupancy drill-down for failed (with live Pods / without live Pods), and the phase mapping.
- Real cluster: against `dynamo-probe` (successful), verify phase=successful, kueue_status=`Admitted` (observed: all three WLs QuotaReserved+Admitted, no PodsReady), status_detail = the raw status as-is, and active_ws kept; recreate a gang with insufficient quota (e.g. gangtest) to verify that phase=pending + kueue_status=QuotaReserved/Queued are written correctly to DDB; **create a failed DGD to observe and finalize the active_ws drill-down rule in §5**.
- DryRun: the controller supports `writer.DryRun`; do a dry run first to check the UpdateItem expression before writing for real.
