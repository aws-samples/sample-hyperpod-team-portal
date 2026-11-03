import { Col, Row, Steps, Typography, theme } from 'antd';
import {
  ApartmentOutlined,
  CodeOutlined,
  ContainerOutlined,
  ControlOutlined,
  DashboardOutlined,
  HomeOutlined,
  KeyOutlined,
  RocketOutlined,
  SafetyCertificateOutlined,
  ShareAltOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import DocPage, {
  ConceptCard,
  DocSection,
  KeyValueList,
  TechBlock,
  UserBlock,
} from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsOverview() {
  const { token } = theme.useToken();

  return (
    <DocPage
      title="HyperPod Platform · Product Overview"
      description="Wraps SageMaker HyperPod + EKS + Kueue into a GPU compute platform: teams get quota per Workspace, and engineers run dev instances, training, and inference in the browser."
      meta={<Text type="secondary">v4.2 · 2026-08-05</Text>}
    >
      <div
        style={{
          padding: '32px 36px',
          borderRadius: 12,
          background:
            'linear-gradient(135deg, #0958d9 0%, #1677ff 50%, #13c2c2 100%)',
          color: '#fff',
          marginBottom: 8,
        }}
      >
        <div style={{ fontSize: 13, opacity: 0.85, letterSpacing: 1, marginBottom: 8 }}>
          HYPERPOD UI PLATFORM
        </div>
        <div style={{ fontSize: 26, fontWeight: 600, lineHeight: '36px', marginBottom: 12 }}>
          An All-in-One Workbench for GPU Training, Inference, and Development
        </div>
        <div style={{ fontSize: 14, lineHeight: '24px', opacity: 0.92, maxWidth: 720 }}>
          Built on AWS SageMaker HyperPod, it provides Workspace isolation · quota management · distributed training
          orchestration · SGLang inference services · cloud Notebook dev instances · Image Hub · Sharing, so ML teams
          can use GPU cluster compute without dealing with K8s / CUDA directly.
        </div>
      </div>

      <DocSection title="What Problems It Solves" subTitle="Why this platform">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              <b>Invisible resources</b>: Many teams share one HyperPod cluster. Who is using the GPUs, how many are
              left, and why tasks are queued: you used to have to SSH into the nodes to find out.
            </li>
            <li>
              <b>Running jobs is too low-level</b>: You face Kubernetes YAML / kubectl / NCCL environment variables
              directly, so newcomers ramp up slowly.
            </li>
            <li>
              <b>Resource abuse / accidental deletion</b>: There is no RBAC and no auditing, and one wrong kubectl
              delete can wipe out someone else's task.
            </li>
            <li>
              <b>Slow dev environment requests</b>: Getting a cloud Notebook used to take a ticket plus manually
              attaching disks.
            </li>
          </ul>
        </UserBlock>
        <TechBlock>
          The platform is a "proxy + wrapper layer" over HyperPod and does not modify the SageMaker control plane:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              <b>Identity / quota</b>: Cognito issues OIDC tokens; AWS CreateComputeQuota automatically creates the
              K8s namespace + Kueue ClusterQueue + ResourceQuota.
            </li>
            <li>
              <b>Scheduling</b>: Kueue ClusterQueue enforces quota, and LocalQueue maps it to the Workspace.
            </li>
            <li>
              <b>Dev instances</b>: Integrates with the amazon-sagemaker-spaces add-on (GA), CRD workspace.jupyter.org.
              The platform only provides the form wrapper + status queries and does not build its own Operator.
            </li>
            <li>
              <b>Training</b>: HyperPod Training Operator + HyperPodPyTorchJob, with hyperpodrun in place of torchrun.
            </li>
            <li>
              <b>Single-node inference</b>: InferenceEndpointConfig (SGLang engine, exposed at three levels: ClusterIP / internal ALB / SageMaker endpoint).
            </li>
            <li>
              <b>Images / sharing / tokens</b>: ECR Image Hub (with online CodeBuild builds) · Sharing (visible within the shared Workspace) · personal API tokens.
            </li>
            <li>
              <b>controller</b>: A standalone Go service (platform-controller): informers for each CR type → derive → DDB writer; the API layer always reads from DDB.
            </li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="Core Modules at a Glance" subTitle="What's in the box">
        <Row gutter={[16, 16]}>
          {[
            {
              icon: <HomeOutlined />,
              title: 'Workspace',
              desc: 'The team isolation unit = K8s namespace + Kueue queue + dedicated FSx + quota',
            },
            {
              icon: <CodeOutlined />,
              title: 'Dev Instance',
              desc: 'Cloud Jupyter / VS Code: launch a GPU-backed Notebook container in one click',
            },
            {
              icon: <ThunderboltOutlined />,
              title: 'Training Job',
              desc: 'Create distributed PyTorch jobs with a sectioned form, managed by hyperpodrun',
            },
            {
              icon: <RocketOutlined />,
              title: 'Inference Service',
              desc: 'Single-node SGLang with an OpenAI-compatible API, loading models from FSx/S3',
            },
            {
              icon: <ContainerOutlined />,
              title: 'Image Hub',
              desc: 'ECR image catalog + online CodeBuild builds, reused by all three task types',
            },
            {
              icon: <ShareAltOutlined />,
              title: 'Sharing',
              desc: 'Share dev instances / training / inference with members of the same Workspace in one click; shared items are read-only',
            },
            {
              icon: <KeyOutlined />,
              title: 'Token Center',
              desc: 'Personal API tokens + kv Secrets, so CLIs/scripts can skip Cognito',
            },
            {
              icon: <DashboardOutlined />,
              title: 'Observability',
              desc: 'GPU/Pod monitoring (filterable by Pod) + live logs / log history + search across all task logs',
            },
            {
              icon: <SafetyCertificateOutlined />,
              title: 'Admin Console',
              desc: 'Task Overview · Priority Class · Workspace Preemption Switch (hidden from regular members)',
            },
            {
              icon: <ApartmentOutlined />,
              title: 'Resource Template',
              desc: 'Maintained per Workspace and shared by all three task types; when creating a task you can only pick one, not enter values by hand',
            },
            {
              icon: <ControlOutlined />,
              title: 'Auditing and Permissions',
              desc: 'Cognito + ABAC; every API call is recorded in a DDB audit table',
            },
          ].map((c) => (
            <Col key={c.title} xs={24} sm={12} lg={6}>
              <ConceptCard icon={c.icon} title={c.title} desc={c.desc} />
            </Col>
          ))}
        </Row>
      </DocSection>

      <DocSection title="A Typical User Journey" subTitle="Day-1 Journey">
        <Paragraph type="secondary" style={{ fontSize: 13 }}>
          The full flow from getting an account to running your first inference service.
        </Paragraph>
        <Steps
          direction="vertical"
          current={-1}
          progressDot
          items={[
            {
              title: 'An admin creates a Workspace',
              description:
                'On the Workspace list, click "New Workspace" → choose instance types/counts → the platform calls CreateComputeQuota → the K8s namespace + Kueue queue are created automatically.',
            },
            {
              title: 'The admin adds members / mounts FSx',
              description:
                'Workspace details page → add users in the "Members" tab; choose shared storage in the "FSx Mounts" tab (each Workspace has its own FSx).',
            },
            {
              title: 'An engineer launches a dev instance',
              description:
                'Dev instance list → "New dev instance" → choose a resource template → open Jupyter Lab in the browser.',
            },
            {
              title: 'Get the script working on the dev instance',
              description: 'In Jupyter, import torch and run on a single GPU to verify the model forward pass / loss.',
            },
            {
              title: 'Submit distributed training',
              description:
                'Training Job → "New training job" → sectioned form (Basic info / Image / Shared storage / Compute resources / Launch configuration / Preview) → Kueue queuing → once Running, check the monitoring.',
            },
            {
              title: 'Deploy an inference service',
              description:
                'Single-node Inference → "New single-node inference" → SGLang + FSx/S3 model path → once it is up, call it with the OpenAI API.',
            },
          ]}
        />
      </DocSection>

      <DocSection title="Recent Updates" subTitle="What's new">
        <Paragraph type="secondary" style={{ fontSize: 13 }}>
          User-visible changes merged into the main line since 2026-07 (only product-facing behavior is listed; for underlying refactors, see the relevant subpages):
        </Paragraph>
        <KeyValueList
          items={[
            {
              k: 'Priority classes now managed through the official mechanism (2026-08-03)',
              v: (
                <>
                  Admin Console → Priority Class: creating, editing, and deleting classes is now handled by the official
                  priority mechanism of SageMaker HyperPod (previously the platform created them in the cluster
                  itself). <b>The way you work does not change</b>: you still enter a name and a value on the same page. There is
                  only one change: the value range is narrowed to <code>0-100</code>, and the description field is now read-only.
                  Running and queued tasks are not affected, and the migration is invisible to users.
                </>
              ),
            },
            {
              k: 'Log history now scrolls much further (2026-07-31)',
              v: (
                <>
                  Previously, log history ran out after a few hundred lines on one screen (a single CloudWatch fetch is capped);
                  now the page scrolls continuously through thousands of lines without breaks, loading 500 lines by default for the first screen and for each further page.
                </>
              ),
            },
            {
              k: 'llm-d multi-node inference launched (2026-08)',
              v: (
                <>
                  Adds a new multi-node inference option, <a href="/docs/llmd">llm-d</a>: a single unified gateway address sits in front, and multiple groups of inference replicas can sit behind it.
                  It suits models that do not fit on a single node when you also want a unified entry point and cache-aware routing.
                  The left menu has a new "Multi-node Inference" entry, and the create form lets you configure the resource specs of the gateway and the inference replicas separately.
                </>
              ),
            },
            {
              k: 'New queue / quota monitoring page (2026-08)',
              v: (
                <>
                  The Monitoring menu has a new "Queue" entry: pick a Workspace to see how much of its compute quota is used, how much is left,
                  and how many tasks are queued. When a task stays Pending for a long time, check here first; it is faster than digging through logs.
                </>
              ),
            },
            {
              k: 'FSx directory quotas (2026-07-22)',
              v: (
                <>
                  The Admin Console has a new "FSx Quota" page: platform admins can set a separate capacity limit for each shared storage directory
                  (writes beyond it are blocked automatically, so one team cannot fill up the disk and affect others).
                </>
              ),
            },
            {
              k: 'FSx usage monitoring (2026-07-22)',
              v: 'The Monitoring menu has a new "FSx Performance" entry: how much storage is used, how much is left, and how busy reads and writes are. Switch freely between 1 hour / 6 hours / 24 hours. All signed-in users can view it.',
            },
            {
              k: 'More accurate instance type info on the quota page (2026-07-24)',
              v: 'The instance type specs (GPU count / model) in the dropdown when creating a quota are now checked by the backend in real time, which fixes the cluster quota overview occasionally showing 0 GPUs.',
            },
            {
              k: 'Image repository names no longer get a forced prefix (2026-07-24)',
              v: 'For online builds in Image Hub, the repository name you enter is used as-is (paths are supported, e.g. team-a/my-model); the platform no longer adds a fixed prefix.',
            },
            {
              k: 'Logs now go back further (2026-07-20)',
              v: 'Log history is now archived automatically to long-term storage, so when troubleshooting you can find records from further back than before.',
            },
          ]}
        />
      </DocSection>

      <DocSection title="Documentation Index" subTitle="Read next">
        <KeyValueList
          items={[
            { k: 'Workspace', v: 'Team isolation + quota + FSx + member management (including how it maps to K8s).' },
            { k: 'Dev Instance', v: 'Cloud Jupyter / VS Code Notebooks. EBS / images / port forwarding / status.' },
            { k: 'Training Job', v: 'Distributed PyTorch + Kueue queuing + hyperpodrun + composite status.' },
            { k: 'Inference Service', v: 'Single-node SGLang, FSx/S3 models, three invocation methods + the full set of deploy/delete states.' },
            { k: 'llm-d Inference', v: 'Cross-node deployment of large models that do not fit on one node, with a unified gateway entry + multiple groups of inference replicas.' },
            { k: 'Image Hub', v: 'ECR catalog + online CodeBuild builds + version tag management.' },
            { k: 'Sharing', v: 'Share dev instances / training / inference with members of the same Workspace; read-only shared list.' },
            { k: 'Token Center', v: 'Personal API tokens + kv Secrets; CLIs/scripts need no sign-in.' },
            { k: 'Admin Console', v: 'Resource Template (per Workspace) · Priority Class · Workspace Preemption Switch · Task Overview.' },
            { k: 'Observability', v: 'Metrics (DCGM + Pod, filterable by Pod) · live logs / log history · Insights search across all task logs.' },
            { k: 'Technical Architecture', v: 'The full picture: EKS + HyperPod + Spaces + Kueue + platform-controller + DDB as the single source of truth.' },
            { k: 'About Permissions', v: 'Three identity types + three decision gates + a capability matrix. After reading it you can answer "who can do what".' },
            { k: 'FAQ', v: 'Troubleshooting tasks stuck in Pending / FSx mounts / hyperpodrun / permissions.' },
          ]}
        />
        <Text type="secondary" style={{ display: 'block', marginTop: 12, fontSize: 12, color: token.colorTextTertiary }}>
          Each subpage is written in two layers, "User view / How it works": the first teaches you how to use a feature, the second explains how it runs underneath.
          The docs entry is in the top-right corner (it opens in a new window); the docs site has its own standalone browsing mode, and internal links work across it.
        </Text>
      </DocSection>
    </DocPage>
  );
}
