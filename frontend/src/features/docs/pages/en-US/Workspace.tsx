import { Typography } from 'antd';
import DocPage, {
  DocSection,
  KeyValueList,
  TechBlock,
  UserBlock,
} from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsWorkspace() {
  return (
    <DocPage
      title="Workspace · Docs"
      description="A Workspace is the smallest isolation unit of the platform: one team = one Workspace = one K8s namespace + one quota + one set of members."
      meta={<Text type="secondary">v2.1 · 2026-07-27</Text>}
    >
      <DocSection title="What It Is" subTitle="Concept" marginTop={0}>
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            Think of a Workspace as "the team's project directory": it holds the team's GPU quota, shared data disks, who
            can get in, and all the dev instances, training jobs, and inference services that run there.
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>A user can join multiple Workspaces (switch between them in the dropdown at the top).</li>
            <li>Workspaces cannot see each other: you cannot see what tasks the team next door is running.</li>
            <li>Quota is accounted per Workspace: once the whole team's GPUs are used up, further tasks queue.</li>
          </ul>
        </UserBlock>
        <TechBlock>
          Each Workspace corresponds to the following in AWS / K8s:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              <code>HyperPod ComputeQuota</code>: a SageMaker control plane object and the source of the quota
            </li>
            <li>
              <code>Namespace</code> <code>hyperpod-ns-{'{name}'}</code>: created automatically by Kueue;
              all Pods / PVCs live here
            </li>
            <li>
              <code>ResourceQuota</code> + <code>LimitRange</code>: native K8s hard limits that keep a
              namespace from taking resources across Workspaces
            </li>
            <li>
              <code>Kueue ClusterQueue + LocalQueue</code>: queuing + priority, mapped one-to-one
            </li>
            <li>
              <code>FSx Lustre mounts</code>: subdirectory isolation prevents cross-tenant reads;
              a Workspace can mount multiple file systems + accept file systems shared by other teams (see "Storage · FSx Lustre" below);
              top-level directories are capped with <code>lfs project</code> quotas and monitored through CloudWatch (see "Storage · FSx Directory Quotas + Monitoring" below)
            </li>
            <li>
              <code>IAM Role</code>: one Role per Workspace (Pod Identity targetTags cannot be used)
            </li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="How to Create One" subTitle="Create a Workspace">
        <UserBlock>
          <ol style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>Click "Workspace" in the left menu → "New Workspace" in the top right (visible only to platform admins).</li>
            <li>Enter the name (slug), display name, and description; the namespace is derived automatically as <code>hyperpod-ns-{'{name}'}</code></li>
            <li>Choose instance types + counts (picked from the instance types available in the cluster; this sets the Workspace's quota).</li>
            <li>After you submit, you land on the details page right away; then mount storage in the "FSx Mounts" tab and add people in the "Members" tab.</li>
          </ol>
        </UserBlock>
        <TechBlock>
          The backend <code>POST /workspaces</code> does 4 things in one transaction:
          <ol style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              Calls AWS{' '}
              <code>SageMaker.CreateComputeQuota</code>: this is the only write operation that touches the SageMaker control plane
            </li>
            <li>
              The SageMaker controller automatically runs <code>kubectl apply</code> to create the namespace + ResourceQuota + ClusterQueue
            </li>
            <li>
              The platform WorkspaceController (lightweight, built in 3 person-days) writes annotations +{' '}
              a Finalizer to the namespace + does drift detection
            </li>
            <li>
              Writes to DDB <code>Workspaces</code> + <code>WorkspaceMembers</code> + <code>AuditLog</code> (three tables)
            </li>
          </ol>
          The whole flow has a P95 &lt; 8s. On failure, <code>CreateComputeQuota</code> is idempotent, so retries are safe.
        </TechBlock>
      </DocSection>

      <DocSection title="Data Model" subTitle="DDB schema">
        <Paragraph type="secondary" style={{ fontSize: 13 }}>
          Workspace metadata uses DDB as the single source; RDS / Redis have been removed.
        </Paragraph>
        <KeyValueList
          items={[
            { k: 'Main table', v: <code>hypd-{'{env}'}-Workspaces</code> },
            { k: 'PK / SK', v: <><code>WS#{'{ws_id}'}</code> / <code>META</code></> },
            { k: 'GSI-1', v: <>by-cluster · looks up the Workspace list by cluster_id</> },
            { k: 'GSI-2', v: <>by-name · uniqueness gate on the slug name (conditional check at creation)</> },
            {
              k: 'Related tables',
              v: (
                <>
                  <code>WorkspaceMembers</code> · <code>ResourceIndex</code> ·{' '}
                  <code>AuditLog</code>
                </>
              ),
            },
            { k: 'TTL', v: 'Workspaces: permanent; AuditLog: 90 days (TTL field)' },
          ]}
        />
      </DocSection>

      <DocSection title="Members and Permissions" subTitle="Membership & RBAC">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              <b>admin (Workspace admin)</b>: adds/removes members, configures FSx, views the Task Overview, adjusts task priority
            </li>
            <li>
              <b>member (regular member)</b>: creates/views their own dev instances, training jobs, and inference services, but cannot change quota/priority
            </li>
            <li>
              There is also the <b>platform admin</b> (across Workspaces): only creates Workspaces + manages the platform-level preemption switch
            </li>
          </ul>
        </UserBlock>
        <TechBlock>
          Permissions are not written to K8s RoleBindings; instead, an ABAC gate is applied in the platform API layer:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              Identity: Cognito ID Token (sub = user_id, custom:is_admin = bool)
            </li>
            <li>
              Roles are looked up in DDB <code>WorkspaceMembers</code> · PK <code>WS#{'{ws_id}'}</code> ·{' '}
              SK <code>USR#{'{user_id}'}</code>
            </li>
            <li>
              All write APIs go through the <code>assert_ws_admin(ws_id, user)</code> decorator; if the check fails → 403 + AuditLog
            </li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="Storage · FSx Lustre" subTitle="Storage · FSx">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            FSx Lustre is the Workspace's high-speed shared disk: training datasets, checkpoints, and code all go here,
            and the Pods of dev instances / training jobs / inference services can all mount the agreed directories for reading and writing.
            Admins maintain mounts in the <b>"FSx Mounts" tab</b> of the Workspace details page; regular members can only use directories they have been granted access to.
          </Paragraph>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>One mount = one directory on one FSx file system</b>. When adding a mount, the admin fills in:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li>
              <b>Mount ID</b> (mount_id): the alias of this disk within the Workspace, starting with a lowercase letter
              (e.g. <code>team-data</code>)
            </li>
            <li>
              <b>Mount point</b> (mount_path): the path inside the Pod's container, which defaults to{' '}
              <code>/fsx/&lt;mount_id&gt;</code> based on the ID and can be changed
            </li>
            <li>
              <b>FSx file system + top-level directory</b>: which subdirectory of which disk to use (you can also enter a deeper subpath by hand)
            </li>
          </ul>
          <Paragraph style={{ marginBottom: 6 }}>
            A Workspace can mount <b>multiple</b> FSx file systems / directories: both "the team's own disks"
            and disks <b>shared</b> by other teams.
          </Paragraph>
          <Paragraph style={{ marginBottom: 0 }}>
            <b>The "Primary" tag</b>: in the FSx list of the create forms, entries with the purple "Primary" tag are <b>the team's own disks</b>{' '}
            (owned by the Workspace's primary group) and are listed first; the rest are <b>other teams' / shared disks</b> you have been granted access to.
          </Paragraph>
        </UserBlock>
        <TechBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>Mounting (attach)</b>: uses <code>fsx-csi-driver</code>. For each mount, the platform creates a pair of
            cluster-scoped PVs (one read-write, one read-only) + a PVC in the Workspace namespace.
            Subdirectory isolation relies on the PV's <code>mountname</code> extending down to the team subdirectory level:
            the Lustre client mounts only that subdirectory, so cross-tenant reads are blocked by the kernel rather than by application logic.
            When a mount is added, the backend <b>probes the owner gid of the directory</b> and pins it into the permission records.
          </Paragraph>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>Granting access (grant)</b>: a mount by itself does not mean members can use it. In the "FSx Mounts" tab, the
            admin <b>grants access to members one by one</b> for each mount, choosing <code>ro</code> (read-only) or <code>rw</code> (read-write).
            Only after being granted access can members see and mount the directory when creating dev instances / training jobs.
          </Paragraph>
          <KeyValueList
            items={[
              { k: 'Grants table', v: <code>hypd-{'{env}'}-MountPermissions</code> },
              {
                k: 'PK / SK',
                v: (
                  <>
                    <code>{'{workspace_id}'}</code> /{' '}
                    <code>MOUNT#{'{mount_id}'}#USER#{'{username}'}</code>
                  </>
                ),
              },
              {
                k: 'GSI',
                v: (
                  <>
                    <code>username-index</code>: used when creating a dev instance to look up "all mounts I have been granted in this Workspace"
                  </>
                ),
              },
              {
                k: 'Key fields',
                v: (
                  <>
                    <code>access</code> (ro/rw) · <code>gid</code> · <code>mount_path</code> ·{' '}
                    <code>pvc_name_rw</code> / <code>pvc_name_ro</code> · <code>granted_by</code>
                  </>
                ),
              },
            ]}
          />
          <Paragraph style={{ marginBottom: 0, marginTop: 8 }}>
            <b>How gid and "Primary" actually work</b>: a Workspace has an inherent primary group{' '}
            <code>primary_gid</code> (= the Pod's <code>runAsGroup</code>, pinned in the
            Workspace metadata the first time FSx is mounted). <code>list_permitted_mounts</code> marks mounts with{' '}
            <code>gid == primary_gid</code> as <code>is_primary=true</code> and puts them first in the list;
            this is where the "Primary" tag in the frontend comes from. The gids of all granted mounts go into the Pod's{' '}
            <code>supplementalGroups</code>, giving the process group-level read/write access to those directories.
          </Paragraph>
        </TechBlock>
      </DocSection>

      <DocSection title="Storage · FSx Directory Quotas + Monitoring" subTitle="FSx quota & monitoring">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>Directory quotas</b> (Admin Console → FSx Quota, platform admins only):
            every top-level directory on each FSx file system connected to the platform has its own project quota,
            which sets how many GiB it can use at most. The overview shows the FS total capacity / used / allocated,
            and the list shows each top-level directory's gid / pid / used / soft / hard / utilization; you can create directories / edit quotas in a dialog.
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li><b>Multiple FSx</b>: pick a file system from the dropdown in the top-right corner of the page (shown as <code>name (fs-id)</code>, where the name comes from AWS Tags[Name]); the first one is selected by default. Creating directories / editing quotas applies to the currently selected one</li>
            <li><b>Create directory</b>: enter the directory name + hard GiB + optionally reuse the gid of an existing team; if no gid is given, the backend allocates a new one automatically (a new team)</li>
            <li><b>soft is automatically = hard × 80%</b> (the warning line)</li>
            <li><b>Capacity constraint</b>: the sum of all directories' hard limits ≤ the total capacity of that file system (validated in both the frontend and the backend, computed per file system)</li>
            <li><b>Edit quota</b>: legacy directories with pid=0 are brought under management along the way (tagged recursively + setquota)</li>
          </ul>
          <Paragraph style={{ marginBottom: 0 }}>
            <b>FSx monitoring</b> (Monitoring → FSx Performance, viewable by all signed-in users): 6 CloudWatch trend charts:
            free capacity / storage utilization / network throughput / disk throughput / disk IOPS / metadata CPU,
            with a time range of 1h / 6h / 24h; the file system is likewise picked from the dropdown in the top-right corner. It is not tied to any Workspace; it is a <b>global view</b>.
          </Paragraph>
        </UserBlock>
        <TechBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>How quotas are applied</b> (<code>app/modules/fsx_quota</code>): through the fsx-admin Deployment (CAP_SYS_ADMIN + lustre-client,
            generated by <code>deploy/cluster-prereq.sh fsxadmin</code>), executed via pod exec (below, <code>&lt;root&gt;</code> = <code>/fsx-mnt/&lt;fs-id&gt;</code>):
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li><code>mkdir &lt;root&gt;/&lt;name&gt;</code> + <code>chown :&lt;gid&gt;</code> + <code>chmod 2770</code> (setgid, so subdirectories inherit the gid)</li>
            <li><code>lfs project -p &lt;pid&gt; -r -s &lt;root&gt;/&lt;name&gt;</code>: sets the project tag</li>
            <li><code>lfs setquota -p &lt;pid&gt; -b &lt;soft&gt;G -B &lt;hard&gt;G &lt;root&gt;</code></li>
          </ul>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>Multiple FSx mounts</b>: <b>one</b> fsx-admin pod mounts <b>multiple</b> file systems, with one PV/PVC pair per file system and
            the mount point <code>/fsx-mnt/&lt;fs-id&gt;</code> (the fs-ids come from the comma-separated list in
            cdk.json <code>platformFsxFilesystems</code>, injected into the backend env <code>PLATFORM_FSX_FILESYSTEMS</code>; fs-ids are inherently path-safe, so they are used directly as mount points).
            A mount point can correspond to only one file system, so a neutral parent directory <code>/fsx-mnt</code> separates them instead of nesting under the root of one of them.
            File systems not configured in <code>PLATFORM_FSX_FILESYSTEMS</code> cannot have quotas (the backend returns an error directly, because it cannot build the mount
            root). <b>Requires Lustre 2.15</b>: on 2.12, project quotas do not take effect (setquota succeeds silently, and the quota reads back as 0).
          </Paragraph>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>gid vs pid</b>: a gid can be reused (sharing team isolation across directories); a pid is always unique (a new pid per directory,
            so each directory can be capped independently). <b>The FS is the source of truth</b>; nothing is stored in DDB.
          </Paragraph>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>Reading usage</b>: a single shell run in one exec fetches <code>lfs project</code> + <code>lfs quota</code> for all directories in parallel
            and parses the output, avoiding multiple execs per directory (from ~3.6s per directory → everything in one fetch).
          </Paragraph>
          <KeyValueList
            items={[
              { k: 'Quota API', v: <><code>GET/POST/PATCH /api/v1/admin/fsx-quota/directories[/&lt;name&gt;]</code> · platform admins · all carry <code>filesystem_id</code> (GET in the query, POST/PATCH in the body)</> },
              { k: 'File system API', v: <><code>GET /api/v1/monitoring/fsx/filesystems</code>: returns <code>{'{filesystemId, name, capacityGib}'}</code> (name = AWS Tags[Name]) for the quota/monitoring page dropdowns, shown as <code>name (fs-id)</code></> },
              { k: 'Monitoring API', v: <><code>GET /api/v1/monitoring/fsx/metrics?filesystem_id=fs-xxx&amp;range=1h|6h|24h</code> · all signed-in users</> },
              { k: 'Monitoring metrics', v: <>6 metrics in one <code>GetMetricData</code> call; extra dimension values (FileServer / StorageTargetId) are first discovered with <code>ListMetrics</code> and then fetched, never hard-coded</> },
              { k: 'Target FSx', v: <>The <code>PLATFORM_FSX_FILESYSTEMS</code> env (<code>fs-id</code>, comma-separated) defines the candidate pool; the frontend dropdown picks a specific one</> },
              { k: 'IAM', v: <>api_role needs <code>cloudwatch:GetMetricData</code> + <code>cloudwatch:ListMetrics</code></> },
            ]}
          />
        </TechBlock>
      </DocSection>

      <DocSection title="List Page Interactions" subTitle="List page UX">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              <b>Summary chip row at the top</b>: Workspaces · Total members · Current total GPU quota usage (M/P GPUs + percentage);
              the numbers are aggregated from the Workspaces you can see, and GPU usage is colored in three bands: &lt;70% / 70-90% / ≥90%
            </li>
            <li>
              <b>GPU row in the card view</b>: progress bar style (same as renderUsageRow on the details page), with the same color thresholds
            </li>
            <li>
              <b>Quick edit entries on cards / list</b> (platform admins only): jump straight to the matching tab of the details page:
              Members / FSx Mounts / S3 Mounts, opened directly via <code>?tab=members|fsx|s3</code> in the URL
            </li>
            <li>
              <b>Switching between list view and card view</b>: the Segmented control in the top-right corner; cards = visual browsing, list = table sorting
            </li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="Storage · S3" subTitle="Storage · S3">
        <UserBlock>
          S3 is used for object storage such as models / datasets: admins add bucket /
          prefix mounts in the Workspace's <b>"S3 Mounts" tab</b>; training jobs can mount and read them directly, and inference services can use them to prefetch models.
          Like FSx, they are managed by <code>mount_id</code> + mount point.
        </UserBlock>
        <TechBlock>
          Uses <code>s3-csi-driver</code> (Mountpoint for S3). Note that S3 mounts have object semantics (not a
          POSIX file system) and suit sequential reads of large files / datasets; for frequent random writes, renames, and appends, use FSx.
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
