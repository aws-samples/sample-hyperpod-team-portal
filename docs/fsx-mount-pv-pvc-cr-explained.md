# FSx Mount Mechanism Explained · PV / PVC / CR Line by Line

**English** | [简体中文](fsx-mount-pv-pvc-cr-explained.zh-CN.md)

> Audience: technical review / operations handover
> Date: 2026-07-17
> Contents: when the platform mounts a subdirectory of the shared FSx for Lustre into a dev instance / training container, what every line of the generated
> PersistentVolume, PersistentVolumeClaim, and Workspace CR means,
> how the three work together, and how read-write / read-only permissions are implemented.

Using team-a's **read-write (rw)** mount as an example (Workspace id `90d7eb44…`, FSx `fs-0c0b…`, subdirectory `team-a`).

---

## 0. Overview of how the three relate

```
Workspace CR (Dev Instance)      PVC                           PV                        FSx
spec.volumes:                    pvc-ws-fsx-team-a-data-rw     pv-...-team-a-data-rw     fs-0c0b
  persistentVolumeClaimName ───► name        ◄── volumeName ──► claimRef points back to PVC
  mountPath: /fsx/team-a-data                                   csi.mountname:            /team-a
  runAsGroup: 5001 ◄─ access via gid                              2no6nb4v/team-a  ────────► subdirectory
                                                                mountOptions: [](rw)
```

- **PV ↔ PVC**: strictly **1:1**, and locked in both directions (the PV's `claimRef` and the PVC's `volumeName` name each other).
- **PVC ↔ Pod**: **1:many** (accessMode=ReadWriteMany; multiple dev instances / training jobs can mount the same PVC at the same time).
- **PV/PVC ↔ FSx subdirectory**: multiple PV/PVC sets can point to the same subdirectory (e.g. an rw set and an ro set), but each PV-PVC pair is still 1:1.

---

## 1. PersistentVolume (PV) — "where this storage actually lives and how to connect to it"

```yaml
apiVersion: v1
kind: PersistentVolume                          # Cluster-scoped resource, does not belong to any namespace
metadata:
  name: pv-ws-90d7eb44-...-fsx-team-a-data-rw   # PV name. Format pv-ws-{workspace-id}-fsx-{mount-id}-{rw|ro}
                                                # Including ws_id + access keeps it unique cluster-wide
  labels:
    hyperpod.io/managed: "true"                 # Platform-created marker (distinguishes it from manually created ones, eases filtering/cleanup)
    hyperpod.io/workspace: team-a               # Which Workspace it belongs to (for humans)
    hyperpod.io/filesystem: fs-0c0b2e...        # Which FSx file system it belongs to
  annotations:
    hyperpod.io/subdir: team-a                  # Records which subdirectory under the FSx root is mounted (platform-internal metadata)
spec:
  capacity:
    storage: 1200Gi                             # Declared capacity. FSx does not actually enforce it (Lustre is a shared pool);
                                                # purely a placeholder (K8s requires a PV to declare a capacity)
  volumeMode: Filesystem                        # Mount as a file system (as opposed to Block = raw block device). FSx uses Filesystem
  accessModes: [ReadWriteMany]                  # RWX: allows multiple nodes/Pods to read and write at the same time.
                                                # Lustre natively supports concurrent multi-client access, hence Many (not RWO)
  persistentVolumeReclaimPolicy: Retain         # What happens to the PV after the PVC is deleted:
                                                # Retain = leave it untouched (FSx data is not deleted, only unbound).
                                                # Never use Delete — it would delete the underlying FSx data as well
  storageClassName: fsx-sc                       # Storage class name. Static binding (the PV is pre-created manually),
                                                # this field only serves to match it with the PVC (both sides must be identical)
  mountOptions: []                              # rw mount: empty. For an ro mount it is ["ro"]
                                                # On the Lustre CSI, only mountOptions:[ro] actually blocks writes;
                                                # the csi.readOnly field has no effect (verified in a POC)
  csi:                                          # Use a CSI driver to connect to the actual storage
    driver: fsx.csi.aws.com                     # AWS FSx CSI driver
    volumeHandle: fs-0c0b2e...-90d7eb44-team-a-data-rw
                                                # The unique identifier of this volume as seen by CSI.
                                                # Format {fs-id}-{ws-id}-{mount-id}-{access}.
                                                # ⚠️ Must be unique cluster-wide: when the same FSx is mounted by multiple PVs,
                                                #   if they all used the bare fs-id, CSI would treat them as the same volume and the second would fail to mount.
                                                #   Appending ws + mount-id + access keeps them distinct
    volumeAttributes:
      dnsname: fs-0c0b2e....fsx.us-west-2.amazonaws.com
                                                # Network address of the FSx (what clients connect to)
      mountname: 2no6nb4v/team-a                # Key! Lustre mount point + subdirectory.
                                                # 2no6nb4v = the FSx root mountname, with /team-a appended
                                                # → only the team-a subdirectory is mounted; the container cannot see the FSx root
                                                #   (other teams' directories), which achieves directory isolation.
                                                # Pod subPath cannot be used — the operator prunes it
  claimRef:                                     # Reverse binding: specifies the only PVC that may use this PV
    namespace: hyperpod-ns-demo              # Namespace of that PVC
    name: pvc-ws-fsx-team-a-data-rw             # Name of that PVC.
                                                # With claimRef set, no other ns/PVC can take this PV
```

---

## 2. PersistentVolumeClaim (PVC) — "my request to use that storage"

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pvc-ws-fsx-team-a-data-rw              # PVC name. Format pvc-ws-fsx-{mount-id}-{rw|ro}.
                                                # This is the name the CR references
  namespace: hyperpod-ns-demo               # A PVC is namespace-scoped (same ns as the Pods that use it)
  labels:                                       # Same markers as the PV, for filtering/management
    hyperpod.io/managed: "true"
    hyperpod.io/workspace: team-a
    hyperpod.io/filesystem: fs-0c0b2e...
spec:
  accessModes: [ReadWriteMany]                  # Must match the PV's accessModes to bind
  storageClassName: fsx-sc                       # Must be identical to the PV's storageClassName
  resources:
    requests:
      storage: 1200Gi                           # Requested capacity, must be ≤ the PV's capacity (equal here)
  volumeName: pv-ws-90d7eb44-...-fsx-team-a-data-rw
                                                # Explicitly names the PV to bind to (static binding).
                                                # Together with the PV's claimRef this forms a two-way lock, one-to-one;
                                                # no dynamic provisioning (no PV is created automatically)
```

**Two-way PV ↔ PVC binding**: the PV's `claimRef` points to the PVC, and the PVC's `volumeName` points to the PV — they name each other, locking the pair together.

---

## 3. Workspace CR (dev instance) — "which PVCs this dev instance mounts, and which identity it runs as"

```yaml
apiVersion: workspace.jupyter.org/v1alpha1
kind: Workspace                                 # The SageMaker Spaces CR for a dev instance
metadata:
  name: alicedev01-th3idttrvp                  # k8s resource name (username + random suffix for uniqueness)
  namespace: hyperpod-ns-demo
spec:
  # ... (other fields such as image / resources / template omitted) ...

  # ── Storage mounts: reference PVCs ──
  volumes:
  - name: vm-fsx-team-a-data                    # Volume name (slug generated from mount_path)
    mountPath: /fsx/team-a-data                 # Where to mount it in the container (the path the user sees inside the container)
    persistentVolumeClaimName: pvc-ws-fsx-team-a-data-rw
                                                # Which PVC to reference. This is a custom field of the Workspace CRD
                                                # (not standard Pod syntax). rw/ro is chosen by the backend based on the granted access

  # ── Permissions / identity: which identity to run as, which groups to belong to ──
  containerSecurityContext:                     # Applies only to the main container (workspace), not to the ssm sidecar
    runAsUser: 1000                             # The process runs as uid 1000 (sagemaker-user, non-root)
    runAsGroup: 5001                            # The process's primary group = 5001 (= this ws's primary_gid = team-a's gid).
                                                # New files belong to this group by default
  podSecurityContext:                           # Pod-level (applies to all volumes of this Pod, not to an individual volume)
    fsGroup: 5001                               # A "fallback" for the primary gid: it takes only one value; K8s tries to chown the root of every volume
                                                # to this group. Useful for a single/primary volume; but when a Pod mounts
                                                # several directories with different gids, it cannot match the others (see the note below);
                                                # what actually makes multiple directories writable is supplementalGroups + each directory's own setgid/gid
    supplementalGroups: [5001, 5002]            # Supplemental groups: the gids of all directories this dev instance mounts are listed here.
                                                # The process "belongs to" all of these groups at once → combined with each directory's own setgid+gid
                                                # (drwxrws---, fixed at creation time), every directory can be read/written according to its group permissions.
                                                # E.g. when mounting team-a (5001) + team-b (5002, shared in) at the same time,
                                                # the process belongs to both groups 5001 and 5002 and can write to both directories
```

> **Division of labor between fsGroup and supplementalGroups (important)**
> - `fsGroup` is **Pod-level, takes only one value, and applies to all volumes** — it does not target any specific volume (which is also why it sits at the same level as `volumes`).
>   When a Pod mounts several directories with different gids, that single fsGroup value can only match one of them (the primary gid); for the other directories it does not match.
>   So it is better thought of as **a fallback for the primary gid**.
> - **What actually guarantees that "the process can write to multiple directories with different gids" is**:
>   1. **`supplementalGroups`** — makes the process a member of all relevant groups at once (5001, 5002, …);
>   2. **The directory's own setgid + gid** (fixed when the directory is created via `chmod 2770 + chown :<gid>`, i.e. `drwxrws--- gid=xxxx`) — each directory's own group ownership is correct, independent of fsGroup.
>   If the process belongs to the directory's gid group + the directory is group-writable → it can write, regardless of fsGroup.

**Operator translation**: the SageMaker Spaces operator reads this CR and translates `spec.volumes[].persistentVolumeClaimName`
into the standard syntax of the actual Pod (generated automatically, no need to write it by hand):

```yaml
volumes:
- name: vm-fsx-team-a-data
  persistentVolumeClaim: { claimName: pvc-ws-fsx-team-a-data-rw }
containers:
- volumeMounts:
  - { name: vm-fsx-team-a-data, mountPath: /fsx/team-a-data }
  securityContext: { runAsUser: 1000, runAsGroup: 5001 }
```

---

## 4. How read-write / read-only is implemented

For the same FSx subdirectory, the platform creates **two PV/PVC sets**:

| PVC | mountOptions of the corresponding PV | Purpose |
|---|---|---|
| `...-team-a-data-rw` | empty | Read-write |
| `...-team-a-data-ro` | `["ro"]` | Read-only (the Lustre CSI blocks writes at the mount layer) |

The grant record (MountPermissions table) stores **both names**, `pvc_name_rw` and `pvc_name_ro`; when a resource is created, the backend picks one based on the user's `access`:
- `access = rw` → mount `pvc_name_rw` (the PV set without the ro option)
- `access = ro` → mount `pvc_name_ro` (the PV set with `mountOptions:[ro]`)

**Permissions have two gates, and both must pass for a write to succeed:**

| Gate | Where | Effect |
|---|---|---|
| 1. PV mount layer | The PV's `mountOptions:[ro]` | An ro mount is entirely read-only; an rw mount lets writes through |
| 2. POSIX group permissions | The CR's `runAsGroup`/`supplementalGroups` + the directory's `setgid + gid` (drwxrws---) | The process belongs to the directory's gid group → read/write per group permissions |

Read-only mount = blocked at gate 1 (using the ro PV/PVC set); normal read-write = both gates let it through (the rw PVC set + the process is in that gid group).

---

## 5. Summary of key design points

| Point | Description |
|---|---|
| **PV↔PVC 1:1** | Two-way lock (claimRef + volumeName); no other ns/PVC can take it |
| **Directory isolation** | Achieved through the PV's `csi.mountname = <lustre-mount>/<subdir>`, which mounts only the subdirectory; **Pod subPath cannot be used** (operator 0.0.16 drops it via structural pruning) |
| **Read-only implementation** | Only the PV's `mountOptions:[ro]` is effective; `csi.readOnly` has no effect on the Lustre CSI |
| **Unique volumeHandle** | `{fs-id}-{ws-id}-{mount-id}-{access}`, preventing collisions when the same FSx is mounted by multiple PVs |
| **reclaimPolicy=Retain** | Deleting the PVC/PV leaves the FSx data untouched; required for shared storage |
| **CR references the PVC** | The Workspace CRD uses the custom field `spec.volumes[].persistentVolumeClaimName`, which the operator then translates into a standard Pod volume |
| **Group permissions** | `runAsGroup` = the ws primary gid (default group of new files); `supplementalGroups` = the gids of all mounted directories (the process belongs to multiple groups); combined with each directory's own setgid+gid (fixed at creation), this isolates read/write by team |
| **Role of fsGroup** | Pod-level, takes only one value, applies to all volumes — it is **a fallback for the primary gid**; writability of multiple directories with different gids relies on `supplementalGroups` + each directory's own setgid/gid, not on fsGroup |
