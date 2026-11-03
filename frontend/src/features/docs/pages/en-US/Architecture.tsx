import { Card, Col, Row, Tag, Typography, theme } from 'antd';
import DocPage, {
  DocSection,
  KeyValueList,
  TechBlock,
  UserBlock,
} from '../../components/DocPage';

const { Text } = Typography;

/** 抽象架构层级一格 — Card + 顶部色条, 与 logo 渐变品牌色统一。 */
function LayerCard({
  layer,
  title,
  items,
  accent = '#0958d9',
}: {
  layer: string;
  title: string;
  items: string[];
  accent?: string;
}) {
  const { token } = theme.useToken();
  return (
    <Card style={{ borderRadius: 12, height: '100%' }} styles={{ body: { padding: 0 } }}>
      <div
        style={{
          height: 6,
          background: `linear-gradient(90deg, ${accent} 0%, #13c2c2 100%)`,
          borderRadius: '12px 12px 0 0',
        }}
      />
      <div style={{ padding: '16px 20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
          <Text style={{ fontSize: 16, fontWeight: 600 }}>{title}</Text>
          <Tag style={{ borderRadius: 4 }} color="blue">
            {layer}
          </Tag>
        </div>
        <ul style={{ paddingLeft: 20, marginBottom: 0, color: token.colorTextSecondary }}>
          {items.map((it) => (
            <li key={it} style={{ fontSize: 13, lineHeight: '22px' }}>
              {it}
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

export default function DocsArchitecture() {
  return (
    <DocPage
      title="Technical Architecture · Docs"
      description="From the React frontend to platform-controller, the EKS control plane, and the SageMaker HyperPod data plane: the full picture, and which boundaries each request crosses."
      meta={<Text type="secondary">v3.2 · 2026-08-05</Text>}
    >
      <DocSection title="The 5-Layer Overview" subTitle="System layers" marginTop={0}>
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} xl={8}>
            <LayerCard
              layer="L4 · Frontend"
              title="Web UI"
              items={[
                'Vite 5 + React 18 + TypeScript 5',
                'Ant Design 5 / ProComponents / ECharts 5',
                'Monaco bundled locally (CDNs are unavailable in the production VPC)',
              ]}
              accent="#0958d9"
            />
          </Col>
          <Col xs={24} sm={12} xl={8}>
            <LayerCard
              layer="L3 · Platform API"
              title="FastAPI Backend"
              items={[
                'Python 3.11 + FastAPI + aioboto3',
                'Business modules (auth/workspace/cluster/quota/training/inference/llmd/devinstance/registry/secret/sharing/logs/...)',
                'A Repository layer hides the DDB schema',
                'DDB-only: status is always read from DDB, never queried directly from K8s',
                'Three OpenAPI views: /api/docs (Swagger) · /api/redoc · /api/scalar',
              ]}
              accent="#1677ff"
            />
          </Col>
          <Col xs={24} sm={12} xl={8}>
            <LayerCard
              layer="L3 · Platform Controller"
              title="Go controller (informer)"
              items={[
                'controller-runtime + client-go informer',
                'Watched CRs: HyperPodPyTorchJob / IEC / LWS(llm-d) / JupyterSpace + Pod',
                'derive/ · status derivation (the six Kueue states + phase composition)',
                'ddb/writer · idempotent write-back to ResourceIndex',
                'mapping/ + gvk/ · unified CR→resource type mapping',
              ]}
              accent="#2f54eb"
            />
          </Col>
          <Col xs={24} sm={12} xl={8}>
            <LayerCard
              layer="L2 · Data plane"
              title="K8s + Kueue + Operator"
              items={[
                'EKS + Kueue ClusterQueue + LocalQueue',
                'amazon-sagemaker-spaces (dev instances)',
                'HyperPod Training Operator (training · hyperpodrun)',
                'InferenceEndpointConfig operator (single-node inference)',
                'KubeRay RayJob (Ray distributed training)',
                'LeaderWorkerSet + sgl-gateway (llm-d multi-node inference)',
                'fsx-admin DaemonSet (lustre-client + lfs project quota)',
                'CodeBuild (online image builds)',
                'Kyverno + ValidatingAdmissionPolicy (replaces the Webhook)',
              ]}
              accent="#13c2c2"
            />
          </Col>
          <Col xs={24} sm={12} xl={8}>
            <LayerCard
              layer="L1 · Infra"
              title="HyperPod + EKS + Networking"
              items={[
                'SageMaker HyperPod cluster (GPU + CPU instance types, configured by admins)',
                'HyperPod task governance ClusterSchedulerConfig (source of truth for priority classes)',
                'VPC private subnets + VPC Endpoints',
                'FSx Lustre (one mounted per Workspace, subdirectory isolation + lfs project quotas on top-level directories) + S3',
                'CloudWatch (FSx metrics · Log Group + subscription → Firehose → S3 archive)',
                'EC2 DescribeInstanceTypes (source of truth for instance type specs, TTL cache, us-east-1)',
              ]}
              accent="#52c41a"
            />
          </Col>
          <Col xs={24} sm={12} xl={8}>
            <LayerCard
              layer="L0 · Storage"
              title="DDB as the Single Source"
              items={[
                'Workspaces / WorkspaceMembers / ResourceIndex',
                'ResourceTemplates / AuditLog / ApiTokens / PlatformAdmins',
                'ResourceShares (cross-user sharing) · WorkspaceImages · ImageBuilds · Secrets',
                'Cognito UserPool (identity; user profile data is not replicated in DDB)',
                'Live AWS API calls instead of an RDS cache',
              ]}
              accent="#722ed1"
            />
          </Col>
          <Col xs={24} sm={12} xl={8}>
            <LayerCard
              layer="L1 · Observability"
              title="AMP + Plan B"
              items={[
                'Amazon Managed Prometheus (metrics)',
                'dcgm-exporter (GPU) + cAdvisor (Pod)',
                'CloudWatch Logs (log history)',
                'ECharts rendered in-house (Plan B, AMG iframe blocked)',
              ]}
              accent="#fa8c16"
            />
          </Col>
        </Row>
      </DocSection>

      <DocSection title="The Lifecycle of a Request" subTitle="Request flow">
        <UserBlock>
          Take "a user viewing the training job list" as an example:
          <ol style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>The browser loads the React app → gets an ID Token from Cognito</li>
            <li>The request carries it as a Bearer Token → the backend list endpoint</li>
            <li>FastAPI first runs <code>assert_ws_member</code> (checks DDB WorkspaceMembers)</li>
            <li>It reads DDB <code>ResourceIndex</code> to get the task list (the phase has already been written by platform-controller)</li>
            <li>On the details page, with <code>sync=true</code>, it also fetches the K8s CR status / Pods live</li>
            <li>It merges DDB metadata + live K8s status → returns JSON</li>
          </ol>
        </UserBlock>
        <TechBlock>
          <b>Why doesn't the API query K8s directly?</b> A standalone controller service (the Go version, <code>services/platform-controller/</code>)
          watches CRs + Pods over long-lived informer connections and, as soon as a status changes, derives the phase and writes it back to DDB.
          The API layer stays stateless with no long-lived connections and only does DDB primary-key reads + permission checks,
          so it scales horizontally freely, needs zero warm-up on cold start, and can serve clients other than the frontend (the CLI / SDK use it too).
          <br />
          For details, see the <code>services/platform-controller/internal/</code> directory: controller / derive / mapping / gvk / ddb.
        </TechBlock>
      </DocSection>

      <DocSection title="Key Architecture Decisions" subTitle="Architecture Decisions">
        <KeyValueList
          items={[
            {
              k: 'Workspace',
              v: 'Workspace reuses the HyperPod team API (CreateComputeQuota automatically creates the ns + queue)',
            },
            {
              k: 'Admission',
              v: 'The Webhook is downgraded to Kyverno + ValidatingAdmissionPolicy (CEL)',
            },
            {
              k: 'Dev instances',
              v: 'DevInstance does not get a home-grown Operator → informer + fallback cleanup',
            },
            {
              k: 'Data store',
              v: 'DDB as the single data source (replaces Aurora + Redis)',
            },
            {
              k: 'Inference access',
              v: 'Inference can optionally use a public SageMaker endpoint (off by default; ClusterIP/ALB only)',
            },
            {
              k: 'GPU monitoring',
              v: 'GPU monitoring is filtered by pod, fixing utilization dilution under fragmented scheduling',
            },
            {
              k: 'Token Center',
              v: 'A standalone center for personal API tokens / kv Secrets, self-managed by each user, so CLIs/scripts need no sign-in',
            },
            {
              k: 'Ray training',
              v: 'Ray training uses the KubeRay RayJob CR, on a par with HyperPodPyTorchJob',
            },
            {
              k: 'Multi-node inference',
              v: 'llm-d multi-node inference (LeaderWorkerSet + sgl-gateway), a CRD separate from single-node IEC',
            },
            {
              k: 'Priority',
              v: 'Priority classes use HyperPod task governance ClusterSchedulerConfig as the single source of truth (no more self-built WPC)',
            },
          ]}
        />
      </DocSection>

      <DocSection title="Why DDB as the Single Source" subTitle="Why no SQL">
        <TechBlock>
          The hard drawbacks of a relational database in this scenario:
          <ol style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>A locked-in min ACU: it burns a fixed monthly cost even with no traffic, which contradicts the pay-as-you-go PaaS cost commitment</li>
            <li>The data shape is "a few metadata tables + live K8s fetches": there is no need for JOINs, and most queries are by primary key</li>
            <li>Every mutation can be written as a conditional_check (CAS), so SQL transactions are not needed</li>
          </ol>
          DDB On-Demand + GSI + TTL meets the needs; RDS + Redis have been removed.
        </TechBlock>
      </DocSection>

      <DocSection title="Deployment Model" subTitle="Deployment">
        <KeyValueList
          items={[
            { k: 'Region', v: 'Outside the China regions (baseline us-west-2; adjust per deployment)' },
            { k: 'Orchestration', v: 'CDK (infra) + container images (platform-api / platform-controller / frontend)' },
            { k: 'Frontend', v: 'Static Vite build output → hosted by nginx, routed by ALB Ingress' },
            { k: 'Remote access', v: 'Instances are in private subnets and accessed via SSM Session Manager / port forwarding' },
          ]}
        />
      </DocSection>
    </DocPage>
  );
}
