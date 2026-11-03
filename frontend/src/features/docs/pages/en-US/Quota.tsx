import { Typography } from 'antd';
import DocPage, {
  DocSection,
  KeyValueList,
  TechBlock,
  UserBlock,
} from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsQuota() {
  return (
    <DocPage
      title="Admin Console · Docs"
      description='Resource templates define "how many GPUs one task can use", quotas define "how much a Workspace has in total", priority classes decide the queue order, and the preemption switch decides whether tasks can be evicted.'
      meta={<Text type="secondary">v3.2 · 2026-08-05</Text>}
    >
      <DocSection title="Three Concepts" subTitle="Vocabulary" marginTop={0}>
        <UserBlock>
          <KeyValueList
            items={[
              {
                k: 'Resource template',
                v: 'A fixed combination of GPU/CPU/memory. When creating a task you can only choose a template, not enter values by hand. The specific instance types are configured by admins (GPU + CPU).',
              },
              {
                k: 'Workspace quota',
                v: "A Workspace's total resource pool (set by instance type × count when the Workspace is created). Tasks that exceed it queue.",
              },
              {
                k: 'Priority class',
                v: 'A platform-level dictionary of classes (maintained by HyperPod task governance; admins create/edit/delete them in the Admin Console) that decides the Kueue queue order. The default is common-priority (weight=80).',
              },
            ]}
          />
        </UserBlock>
        <TechBlock>
          How they map to the Kueue resource model:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>Resource template → the Pod's resources triple (req=lim for inference), which is also the podSet of the Kueue Workload</li>
            <li>Workspace quota → ClusterQueue resourceGroups + LocalQueue mapping</li>
            <li>Priority → HyperPod ClusterSchedulerConfig.PriorityClasses (bare name + weight 0-100) → the platform automatically appends the <code>-priority</code> suffix and maps it to a Kueue WorkloadPriorityClass</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="Resource Templates" subTitle="Templates">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            Resource templates are <b>maintained per Workspace</b>. The entry is "Resource Template" in the left menu (visible once a Workspace is selected;
            all members can view; only Workspace admins or platform admins can create/edit/delete). Switching Workspaces shows a different template list.
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>New template: enter a name + GPU count + CPU cores + memory GiB (GPU limit 8 per node)</li>
            <li>The three task types (dev instance / training / inference) share one set of templates (decided on 2026-06-14)</li>
            <li>GPUs can be 0 (CPU-only tasks)</li>
            <li>When creating a task, users can only choose a template and cannot enter CPU/GPU/memory by hand (inference req=lim, no distinction)</li>
          </ul>
        </UserBlock>
        <TechBlock>
          DDB table <code>{'{prefix}'}-ResourceTemplates</code> (partitioned by ws_id). The backend service layer
          decides write permission with <code>is_ws_admin</code> (platform admin OR role=admin in the current Workspace), consistent with the frontend entry points.
          Templates are the real enforcement layer: when a task is created, its resources are set by the selected template and cannot be entered by hand.
        </TechBlock>
      </DocSection>

      <DocSection title="Workspace Quota · Instance Specs" subTitle="Instance spec source of truth">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>Since 2026-07-24</b>, the instance type specs (GPU count / model / vCPU / memory) in the dropdown when creating a quota all come authoritatively from the backend;
            the frontend no longer maintains a static instance type table. After you select a cluster, the instance type dropdown only lists <b>instance types that actually exist in that cluster</b>,
            each with a spec chip (e.g. <code>ml.p5.48xlarge · 8×H100 · 192 vCPU · 2048 GiB</code>) for comparison.
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>The cluster quota overview (across Workspaces) also shows the aggregated specs of each quota; the bug where it occasionally showed 0 GPUs has been fixed</li>
            <li><b>Trainium does not support pool separation yet</b>: NeuronInfo is currently not counted as accelerators, so Trainium instance types only appear in the CPU pool</li>
          </ul>
        </UserBlock>
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              Data source: EC2 <code>DescribeInstanceTypes</code> (hard-coded to us-east-1, TTL cache),
              extended through <code>InstanceSpec</code> with extra fields (vCPU / memory GiB / GPU model) and then filled back into quota resources / cluster instance-groups
            </li>
            <li>
              Endpoint contract: the resources[] returned by <code>GET/POST/PATCH /workspaces/&#123;id&#125;/quota</code> and
              {' '}<code>GET /clusters/&#123;tag&#125;/quotas</code> all carry pool/gpu_spec/gpu_type/vCpu/memoryInGib
            </li>
            <li>The old frontend file <code>instance-types.ts</code> has been deleted; Dashboard / QuotaResourcePicker / the Cluster page now all read pool information from the backend</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="FSx Directory Quotas" subTitle="FSx project quota">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>Left menu · Admin Console → FSx Quota</b> (visible only to platform admins).
            Maintains separate quotas for all <b>top-level directories</b> (<code>/fsx/&lt;team&gt;</code>) on the platform's FSx;
            the source is the Lustre <code>lfs project</code> quota.
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li>Overview at the top: FS total capacity / used / allocated (sum of all directories' hard limits)</li>
            <li>
              "Create directory" dialog: enter the directory name + hard GiB + optionally <b>reuse the gid of an existing team</b>{' '}
              (sharing isolation across directories) or let the backend <b>allocate a new one automatically</b>
            </li>
            <li>"Edit quota" dialog: only adjusts hard; soft is automatically = hard × 80% (the warning line)</li>
            <li>The sum of all directories' hard limits must not exceed the FS total capacity (validated in both the frontend and the backend)</li>
            <li>Existing legacy directories (pid=0, not managed) are brought under management along the way when you use "Edit quota": project tag applied recursively + setquota</li>
          </ul>
          <Paragraph style={{ marginBottom: 0 }}>
            Monitoring metrics (storage usage / free / throughput / IOPS) live separately under <b>Left menu · Monitoring → FSx Performance</b>,
            viewable by all signed-in users (it is a global view, not tied to any Workspace).
          </Paragraph>
        </UserBlock>
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              Backend <code>app/modules/fsx_quota</code>: through the <code>fsx-admin.yaml</code> DaemonSet
              (CAP_SYS_ADMIN + lustre-client), pod exec
              runs <code>mkdir</code> / <code>chown</code> / <code>chmod 2770</code> (setgid) / <code>lfs project -s -r</code> / <code>lfs setquota</code>
            </li>
            <li>
              <b>gid vs pid</b>: a gid can be reused (sharing team isolation across directories); a pid is always unique (a new pid per directory)
            </li>
            <li>
              Reading usage: a single shell run in one exec fetches all directories in parallel + parses the output, avoiding multiple execs per directory
              (~3.6s per directory → everything in one fetch)
            </li>
            <li>
              <b>The FS is the source of truth</b>; nothing is stored in DDB (completely independent of the DDB + K8s CR setup used for ComputeQuota)
            </li>
            <li>
              Monitoring uses CloudWatch <code>GetMetricData</code> + metric math (single dimension FileSystemId),
              with three windows: 1h/6h/24h
            </li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="Priority Classes" subTitle="Priority classes">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>Left menu · Admin Console → Priority Class</b> (visible only to platform admins). Priority classes are a
            dictionary <b>shared by all Workspaces on the platform</b>: every task picks its class from this list.
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              When creating/editing a class, enter a <b>bare name + weight (0-100)</b>; the platform automatically appends the <code>-priority</code> suffix in the cluster
              (e.g. creating <code>training</code> → the cluster gets <code>training-priority</code>)
            </li>
            <li><b>The weight is a relative value</b>: larger means higher priority; it does not represent minutes or a percentage of quota</li>
            <li>
              The value shows up in two ways:
              (1) when tasks queue, tasks with a larger weight go first;
              (2) in Workspaces where the preemption switch is on, tasks in a higher-weight class can evict running tasks in a lower-weight class
            </li>
            <li>
              Changing a class's weight <b>only affects tasks submitted afterwards</b>; tasks already running/queued keep the weight snapshot from when they were submitted and are not recalculated
            </li>
            <li>
              All task types (training / inference / llm-d / Ray Job / dev instance) use <code>common-priority</code> (weight=80) by default; do not delete it
            </li>
            <li>
              The description field is now <b>read-only</b> (the official API does not accept this field)
            </li>
          </ul>
        </UserBlock>
        <TechBlock>
          The single authoritative source: the cluster policy of SageMaker HyperPod task governance (<code>ClusterSchedulerConfig</code>).
          The platform <b>no longer writes K8s WorkloadPriorityClasses itself</b>; instead it reads and writes this cluster policy through the official API,
          and the official HyperPod reconciler generates/updates the actual WPCs from it. The default class names of the six task types have been consolidated into a unified per-task-type configuration;
          task types that are not configured fall back to the global default class.
        </TechBlock>
      </DocSection>

      <DocSection title="Workspace Preemption Switch" subTitle="Per-workspace preemption">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>Left menu · Admin Console → Workspace Preemption Switch</b> (visible only to platform admins). Each Workspace has one switch per row,
            which decides whether, within that Workspace, tasks in a higher priority class can evict running tasks in a lower priority class when the quota is used up.
          </Paragraph>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>When does preemption happen?</b> All three conditions below must be met at the same time; if any one is not met, it will not happen:
          </Paragraph>
          <ol style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li>The preemption switch of this Workspace is on (LowerPriority)</li>
            <li>The compute quota of this Workspace is used up</li>
            <li>A task in a higher priority class is queued in the same Workspace</li>
          </ol>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>Preemption boundaries</b>:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>Preemption only takes effect inside a single Workspace; Workspaces do not affect each other</li>
            <li>Preemption evicts the task's containers, but the task itself is kept; its queue status becomes Evicted and it then re-enters the queue</li>
            <li>A preempted training job is re-queued automatically, but it can only resume training if checkpoint fault tolerance is configured on the training side</li>
            <li>When an inference service or dev instance is preempted, the online service or user session is interrupted</li>
          </ul>
        </UserBlock>
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              ClusterQueue <code>spec.preemption.withinClusterQueue</code> = Never / LowerPriority,
              set per Workspace (one Workspace maps to one cq, resolved from the namespace)
            </li>
            <li>
              There is also the AWS-level <code>PreemptTeamTasks</code> (cross-team preemption); the platform defaults it to Never and does not expose a toggle in the UI, so Workspaces do not affect each other
            </li>
            <li>Preemption decisions are made by the Kueue controller; the platform only passes the switch through</li>
            <li>The Workload of a preempted task is marked Evicted (visible in the "Queue status" column in the frontend) and re-queued to wait for free resources</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="Changing a Task's Priority Class" subTitle="Edit task priority">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>Changing the class of a specific task is not done in the Admin Console</b>; it is done by a <b>Workspace admin or platform admin</b> on that
            Workspace's <b>"Task Overview"</b> page (click the pencil icon in the task row's priority class column).
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              Changing the class of a <b>queued</b> task: it is re-queued immediately under the new class, higher classes move forward, and the task does not restart
            </li>
            <li>
              Changing the class of a <b>running</b> task: the platform recreates the task's containers so the new class takes effect; training jobs are re-queued automatically
              (they can only resume training if they have checkpoints); for inference / dev instances, this means a service interruption / session interruption
            </li>
            <li>
              Changing the class itself <b>does not trigger preemption</b>: for running tasks to be evicted automatically, you also need to turn on this Workspace's switch in "Admin Console → Workspace Preemption Switch"
            </li>
          </ul>
        </UserBlock>
        <TechBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            Kueue does not allow changing the priority of an in-flight Workload directly, so "changing the class of a running task" actually means:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>Training: patch the CR's priority-class label + delete the Workload; Kueue recreates the Workload from the new label</li>
            <li>Dev instance/inference: patch the CR label + delete the Deployment; the Operator recreates the Deployment from the new label → new Pods</li>
            <li>Queued tasks: after the label changes, Kueue re-sorts them automatically, with no need to recreate containers</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="Task Overview Page" subTitle="Tasks console">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>Admin Console → Task Overview</b> (visible to Workspace admins / platform admins, hidden from regular members; you must select a Workspace first).
            View all <b>active</b> tasks in this Workspace across types (dev instance / training / inference) and adjust the Kueue queue priority.
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              <b>Queue position column</b> (shown only when the scope is "Queued"): the real position in the Kueue LocalQueue (1 = head of the queue),
              from <code>positionInLocalQueue</code> in the Kueue visibility API; the order is decided by priority class + submission time
            </li>
            <li>
              <b>Status column</b>: each task's own lifecycle (dev instance Available / training Running / inference DeploymentComplete, and so on),
              showing the raw CR phase without normalization. Composite statuses may appear, such as <code>Created/Running</code>
            </li>
            <li>
              <b>Filters</b>: Scope (Queued / Running / All) + Type (dev instance / training / inference) + task name search
            </li>
            <li>
              <b>Changing the class</b>: click the pencil icon in the priority class column; it is only clickable for queued tasks (running tasks need the Workload deleted and recreated, which has separate logic)
            </li>
          </ul>
        </UserBlock>
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>Permission: the backend GET /tasks goes through assert_ws_admin (platform admin OR ws role=admin); if the check fails, it returns 403</li>
            <li>Queue position: the Kueue visibility extension API (not a regular CRD); the backend uses a raw call_api to get pendingworkloads</li>
            <li>Changing the class goes through the priority module; see the previous section, "Changing a Task's Priority Class"</li>
            <li>The overview only shows active_only tasks (queued + running, excluding succeeded / failed)</li>
          </ul>
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
