# FSx Storage · Directory Quota Design

**English** | [简体中文](fsx-storage-quota-design.zh-CN.md)

> Audience: users / design review
> Date: 2026-07-16
> Status: UI demo completed; the underlying mechanism has been verified end to end; to be integrated after sign-off

---

## 1. Problem to solve

The platform uses a **shared FSx for Lustre** file system, partitioned into usage space by **top-level directory (one directory per team)**:

```
<FSx root>
├── team-a/     ← NLP team
├── team-b/     ← Vision team
├── team-c/     ← Training data
└── team-d/     ← ...
```

The platform can connect **multiple** FSx file systems at once (comma-separated fs-ids in the configuration). Quotas are **independent per file system**: each file system has
its own set of top-level directories + its own capacity limits; on the page you first select a file system, then view/edit the directory quotas of that file system.

Current problem: **there are no storage quotas** — any single team can fill up an entire FSx and affect the other teams. We need to:

1. **Set a storage limit on each top-level directory** (hard quota: writes are rejected once exceeded, not just a warning).
2. **Monitor in real time** the usage vs. quota of each directory, so you can see at a glance who is almost full and who is over.
3. Let admins **create directories and set quotas directly in the platform UI**, without logging in to a server and typing commands.

---

## 2. Solution overview

Add an "FSx Storage" page to the **Admin Console**, offering two capabilities:

### 2.1 Create directory (one click, automated)
The admin fills in only two fields: **directory name** + **quota size**. The platform backend automatically:
- Creates the top-level directory on FSx
- Assigns a POSIX group ID (gid) + sets the setgid permission (members of the team can read and write, without interfering with each other)
- Applies a Lustre project tag + sets a hard storage quota

### 2.2 Usage monitoring
Lists all top-level directories in a table: directory name, gid, **used/quota (progress bar)**, status (Normal / Near limit / Over quota), and file count. Directories that are nearly full or over quota are highlighted in prominent colors.

---

## 3. Underlying technical mechanism

### 3.1 Quota type: Lustre Project Quota

FSx for Lustre (from **version 2.15**) supports three quota types: user / group / **project**. This design uses **project quota**:

- **Limits by directory tree**: tag a directory with a project id, and the total usage of that directory and all its descendant files is limited by that project's quota.
- **Hard limit**: once usage reaches the limit, further writes are rejected by the file system (`Disk quota exceeded`), fundamentally preventing the file system from filling up.
- **Real-time accounting**: Lustre maintains usage counters per project (capacity + file count); reads take milliseconds and do not traverse the directory.

> Prerequisite: project quota requires a file system **natively created as 2.15** (already in place for this project).

### 3.2 Execution vehicle: the fsx-admin management Pod

The platform has a long-running **fsx-admin Pod**; the backend uses it to run Lustre commands that create directories and set and read quotas.

- **One Pod mounts multiple file systems**: each FSx is mounted at its own mount point `/fsx-mnt/<fs-id>` (a mount point can correspond to only
  one file system, hence one directory per fs-id; a neutral parent directory `/fsx-mnt` is used instead of nesting under one file system's root, to avoid polluting that file system).
  Every quota operation from the backend carries the target file system id, which is internally mapped to the corresponding mount root.
- The Pod is **not exposed externally** (no ports, no external entry point); it only runs the fixed commands issued by the platform backend.
- Setting quotas requires the Linux `CAP_SYS_ADMIN` capability (a kernel requirement of the Lustre quota system call; it cannot be replaced by a smaller privilege).
- Dev instances / training jobs mount FSx **without going through** this Pod (each has its own PV/PVC), so mount point changes only affect quota management.

### 3.3 Permissions and security

| Item | Description |
|---|---|
| **Quota operation privilege** | The fsx-admin Pod needs `CAP_SYS_ADMIN` (only this one capability, not full privileged mode). It is used only for quota management; the Pod is not exposed externally, so the attack surface is small. |
| **AWS IAM** | Quotas are file system data-plane operations and **do not require any additional AWS IAM permissions**. |
| **Who can operate** | Platform admins only (on the Admin Console page). |
| **Who the quotas apply to** | Each team's dev instances / training jobs (which write data as regular users) are subject to the hard quota limits. |

---

## 4. UI mockup (UI demo completed)

**Page: Admin Console → FSx Storage**

**File system selector at the top right**: when multiple FSx file systems are connected, first select one from the dropdown (showing the FSx name + fs-id); the first one is selected by default. The overview and
table below all show data for the currently selected file system.

**Overview at the top**: FSx total capacity / Total used / Directories / Over-quota directories

**Create directory** (modal, only two fields):
- Directory name (e.g. `team-e`)
- Quota size (e.g. `100 GiB`)
- gid / permissions / project tag are assigned automatically by the backend

**Usage monitoring table**:

| Directory | GID | Usage / Quota | Status | Files |
|---|---|---|---|---|
| /team-a · NLP team | 5001 | ▓▓▓▓▓▓▓░░ 342 / 500 GiB (68%) | ✅ Normal | 128,400 |
| /team-b · Vision team | 5002 | ▓▓▓▓▓▓▓▓▓ 96 / 100 GiB (96%) | ⚠️ Near limit | 40,100 |
| /team-c · Training data | 5003 | ▓▓▓▓▓▓▓▓▓▓ 210 / 200 GiB (105%) | ❌ Over quota | 88,000 |
| /team-d | 5004 | ▓░░░░░░░░ 12 / 200 GiB (6%) | ✅ Normal | 3,200 |

- Progress bar + percentage give an intuitive view of usage
- Status thresholds: < 80% Normal (green), ≥ 80% Near limit (yellow, aligned with the soft limit), ≥ 100% Over quota (red)
- Status is conveyed three ways: icon + text + color

---

## 5. Possible future extensions (optional)

- **FSx performance/storage monitoring charts**: integrate CloudWatch metrics (storage utilization, throughput, IOPS, network, etc.) and show trend charts on this page. Technically feasible (backend pulls from CloudWatch + frontend charts); a separate incremental piece of work.

---

## Appendix A: Underlying command list (technical reference)

The following commands are run by the backend through the fsx-admin Pod, and all have been verified in a real environment.
Below, `<root>` = the mount root of the target file system inside the fsx-admin Pod, `/fsx-mnt/<fs-id>`.
gids are allocated starting at 5001 and project ids starting at 6001 (different thousand ranges, so the two are easy to tell apart at a glance).

### Create directory + set quota
```sh
# Example: directory team-e, assign gid=5005, project id=6005, quota 100GiB
mkdir <root>/team-e
chown :5005 <root>/team-e               # group=5005
chmod 2770 <root>/team-e                # setgid + rwxrws--- (group read/write, new files inherit the gid)
lfs project -p 6005 -r -s <root>/team-e # apply the project tag (-r recursive, -s inherit)
lfs setquota -p 6005 -b 80G -B 100G <root>   # -b soft limit (80% of hard limit) -B hard limit
```

### View usage (monitoring / refresh)
```sh
lfs quota -p 6005 <root>
# Output (~2ms, no directory traversal):
#   Filesystem  kbytes   quota      limit       grace  files   quota  limit  grace
#   /fsx-mnt/fs-0aaa
#               977439   85899345   104857600   -      293     0      0      -
#   kbytes=used KB  quota=soft limit KB  limit=hard limit KB  files=file count
# ⚠️ When the mount root path is long, lfs puts Filesystem on its own line and the values on the next line (as above);
#    when the path is short they are on the same line. The parser must handle both layouts, otherwise all usage reads as 0.
#    Values that exceed the limit carry a trailing `*` marker, which must be stripped before converting to a number.
```

### Change quota
```sh
lfs setquota -p 6005 -b 160G -B 200G <root>   # overwrite with 200GiB
```

### Delete directory / clear quota
```sh
lfs setquota -p 6005 -b 0 -B 0 <root>   # clear the quota (0 = unlimited)
lfs project -p 0 -r -s <root>/team-e    # remove the project tag
rm -rf <root>/team-e                    # delete the directory (only run on a UI delete action + second confirmation)
```

### Helpers
```sh
ls -lan <root>                          # list top-level directories + gid
lfs project -d <root>/team-e            # show the directory's project id → "6005 P <root>/team-e"
lfs quota -t -p <root>                  # show the grace period of project quota
```

---

## Appendix B: Key design trade-offs

| Decision | Conclusion | Reason |
|---|---|---|
| project quota vs group quota | **project quota** | Limits by directory tree, more flexible, not tightly bound to the directory gid |
| Hard quota vs soft quota | **Hard quota** | Enforced at the file system layer, so writes really are rejected once exceeded; a soft quota (warning only) can be bypassed by users |
| Data source | fsx-admin Pod runs `lfs` commands | Lustre quotas are data-plane operations and do not go through the AWS API |
| Privilege | `CAP_SYS_ADMIN` only | A hard kernel requirement of `quotactl`; already the least privilege (not full privileged mode) |
| File system | Native 2.15 FSx | Project quota is only available on native 2.15. The FSx console **creates 2.12 by default**; on 2.12, `lfs setquota` appears to succeed but the quota does not take effect (`lfs quota` returns `Operation not supported` / all 0), so 2.15 must be explicitly selected when creating the file system |
| Multi-file-system mounting | One fsx-admin Pod mounts multiple, at `/fsx-mnt/<fs-id>` | A mount point can correspond to only one file system; sharing one Pod saves resources, and all quota operations run in the same place |
| File system identifier | Comma-separated `fs-id` in the configuration, with the fs-id as the mount point; the UI displays AWS `Tags[Name]` | An fs-id (`fs-<hex>`) is inherently path-safe and can be used directly as a path segment, avoiding the validation/uniqueness burden of manual aliases; the display name comes from the FSx's own Name tag, so nothing extra needs to be maintained |
