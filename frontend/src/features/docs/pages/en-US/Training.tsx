import { Steps, Typography } from 'antd';
import DocPage, {
  DocSection,
  KeyValueList,
  TechBlock,
  UserBlock,
} from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsTraining() {
  return (
    <DocPage
      title="Training Job · Docs"
      description="Distributed training orchestration based on the HyperPod Training Operator, from a single GPU to multi-node DDP, fully web-based with no SSH needed."
      meta={<Text type="secondary">v3 · 2026-06-25</Text>}
    >
      <DocSection title="What It Is" subTitle="Concept" marginTop={0}>
        <UserBlock>
          A training job = one <code>HyperPodPyTorchJob</code> + a set of worker Pods.
          Fill in the form and the platform takes care of the rest: Kueue queuing → image pull → scheduling onto GPU nodes → mounting FSx/S3 → running your launch command.
          The details page shows Pod status, live logs, and GPU monitoring, and you can also open a Pod terminal for debugging.
        </UserBlock>
        <TechBlock>
          Key technology stack:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              CRD: HyperPod Training Operator + <code>HyperPodPyTorchJob</code> (not the Kubeflow PyTorchJob)
            </li>
            <li>
              Launcher: <code>hyperpodrun</code> (replaces torchrun): starts the HyperPodElasticAgent on :8080 inside the Pod,
              which the operator relies on to decide that training is complete. Jobs whose command does not include hyperpodrun are restarted over and over (see the "Launch Command and hyperpodrun" section)
            </li>
            <li>
              Queuing: Kueue ClusterQueue + LocalQueue (one LocalQueue per Workspace)
            </li>
            <li>
              Status: the platform-worker informer watches the CR <code>status.conditions</code> → derives the phase and writes it to DDB
            </li>
            <li>
              Instance types are configured by admins (through resource templates). Multi-node GPU communication uses NCCL
            </li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="Create Form" subTitle="Create form">
        <Paragraph type="secondary" style={{ fontSize: 13 }}>
          A single page filled in section by section (not a step-by-step wizard), with anchor links on the right. Each section maps to part of the CR fields.
        </Paragraph>
        <Steps
          direction="vertical"
          current={-1}
          items={[
            {
              title: 'Basic info',
              description: 'Display name + job name (derived from the display name, DNS-friendly) + description. The Workspace is the one selected in the dropdown at the top.',
            },
            {
              title: 'Image',
              description:
                'A base image (default pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime) or a private ECR image (repo:tag).',
            },
            {
              title: 'Shared storage',
              description:
                'Mount multiple FSx / S3 locations (select the ones you have been granted). Put code, data, and checkpoint output on the mounted FSx and write the paths in the launch command yourself; the platform does not integrate with Git.',
            },
            {
              title: 'Compute resources',
              description:
                'Choose a resource template (maintained by admins) → it fills in the instance type + GPU/CPU/memory per node. Enter the node count yourself (multiple nodes = distributed). GPUs can be 0 (CPU-only jobs).',
            },
            {
              title: 'Launch configuration',
              description:
                'Write the entire launch script directly (Monaco editor). By default the platform wraps it in /bin/bash -lc, so shell syntax is supported.',
            },
            {
              title: 'Preview',
              description: 'Before submitting, review the rendered HyperPodPyTorchJob YAML: what you see is what you get.',
            },
          ]}
        />
      </DocSection>

      <DocSection title="Launch Command and hyperpodrun" subTitle="Launch command">
        <UserBlock>
          Whatever you put in the launch command field, the container runs with bash. Two typical forms:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              Script path: <code>bash /fsx/&lt;your-disk&gt;/code/train/start.sh</code> (keep the script on FSx and manage dependencies and startup yourself)
            </li>
            <li>
              Direct command: <code>python /fsx/.../train.py --epochs 10</code>
            </li>
          </ul>
          For training to "complete normally" (instead of restarting over and over), the command must be launched through <code>hyperpodrun</code>.
        </UserBlock>
        <TechBlock>
          Verified in testing (DT-19): the HyperPodPyTorchJob operator decides "complete" only from reports by the
          HyperPodElasticAgent on :8080 inside the Pod; it does not look at the container exit code.
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              The command includes <code>hyperpodrun</code> (starts the agent) → the agent reports when training ends → the Job is marked Completed
            </li>
            <li>
              Bare command (no hyperpodrun) → no agent → the operator considers it "never really started", and when the Pod exits it is
              brought back up by restartPolicy=Always → endless restarts
            </li>
            <li>
              Non-torch commands can be hosted too: <code>hyperpodrun ... --no-python /bin/bash -c '&lt;cmd&gt;'</code>
            </li>
          </ul>
          Your own scripts (such as start.sh) can simply call hyperpodrun internally; the platform does not force automatic wrapping (auto_wrap is off by default).
        </TechBlock>
      </DocSection>

      <DocSection title="Status" subTitle="Status">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            The list and details pages show <b>two kinds of status</b>, which coexist and mean different things. For details, see the "Status guide" tip that expands from the ? icon on the list page:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li>
              <b>Task status</b> (CR phase): the job's own lifecycle.
              Typically <code>Suspended (suspended by Kueue) → Created → Created/Running (running) → Created/Completed → Complete</code>;
              on failure it becomes <code>Failed</code>; during automatic fault retries it is <code>Faulted</code>
            </li>
            <li>
              <b>Queue status</b> (Kueue's six states): where the job is in the scheduling
              queue. <code>Queued → QuotaReserved → Admitted → PodsReady</code>; when preempted it becomes <code>Evicted</code>;
              when finished it becomes <code>Finished</code>
            </li>
            <li>
              Occasionally a <b>composite status</b> such as <code>Created/Running</code> appears: when several conditions are True at the same moment, their type names are joined with /
            </li>
            <li>
              The list page has two independent filters, by task status and by queue status, and the chips show counts
            </li>
            <li>
              The Pod table on the details page shows each Pod's READY / status / restart count / exit reason (OOMKilled, Evicted, exit code, and so on)
            </li>
          </ul>
        </UserBlock>
        <TechBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            The phase is derived by the platform-worker informer from the CR <code>status.conditions</code>:
            it takes all conditions with status==True and picks one by most recent lastTransitionTime first + a fixed priority
            (terminal&gt;running&gt;created&gt;suspended); when timestamps are exactly equal, the type names are joined with / to form a composite status.
            The priority table <code>worker/phase.py:_CR_PHASE_PRIORITY</code> fully
            covers <code> Failed / Complete / Completed / Succeeded / Running / Created / PodsRunning / Faulted / Suspended</code>.
          </Paragraph>
          <Paragraph style={{ marginBottom: 0 }}>
            kueue_status is a pure mirror of the Workload <code>status.conditions</code> (six-state priority: Finished &gt; Evicted &gt;
            PodsReady &gt; Admitted &gt; QuotaReserved &gt; Queued). Old DDB data still has lowercase values from the migration period
            (<code>queued / started / finished</code>), which the backend <code>is_terminal</code> handles.
            Pod-level status is fetched from k8s in real time when the details page syncs.
          </Paragraph>
        </TechBlock>
      </DocSection>

      <DocSection title="Multi-node Training / NCCL" subTitle="Distributed">
        <UserBlock>
          Node count &gt; 1 = multi-node distributed (one Pod per node). Nodes synchronize gradients with NCCL all-reduce.
        </UserBlock>
        <TechBlock>
          <KeyValueList
            items={[
              { k: 'Criterion', v: <>WORLD_SIZE &gt; 1 + a shared MASTER_ADDR (verified with 2 nodes × 2 GPUs communicating across nodes)</> },
              { k: 'NCCL', v: 'Built into the image; multi-node handshake is automatic' },
              {
                k: 'EFA',
                v: 'Whether the EFA high-speed network is used depends on the instance type: some instance types have no EFA and use the regular network; only high-end GPU instance types have it',
              },
              {
                k: 'GPU monitoring',
                v: 'The Monitoring tab on the details page filters by Pod, so utilization is not diluted by GPUs of other tasks on the same node',
              },
            ]}
          />
        </TechBlock>
      </DocSection>

      <DocSection title="Checkpoint / Resume" subTitle="Checkpoint">
        <UserBlock>
          Currently: checkpoints are saved by your training script to the mounted FSx (you choose the path); when a HyperPod node fails,
          the operator's auto-resume automatically reschedules and reruns the job. If it crashes, you can also resubmit it from the details page.
        </UserBlock>
        <TechBlock>
          Platform-side checkpoint management (sidecar SDK + REST reporting) is on the roadmap but <b>not implemented yet</b>:
          there is no checkpoint sidecar and no <code>/trainings/&#123;id&#125;/checkpoints</code> endpoint.
          For now, checkpoints are managed entirely by your scripts (written to FSx), and the platform does not get involved.
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
