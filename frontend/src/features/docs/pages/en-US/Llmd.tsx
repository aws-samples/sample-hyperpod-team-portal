import { Typography } from 'antd';
import DocPage, {
  DocSection,
  KeyValueList,
  TechBlock,
  UserBlock,
} from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsLlmd() {
  return (
    <DocPage
      title="llm-d Inference · Docs"
      description="Cross-node deployment for large models that do not fit on one node: a Gateway sits in front, multiple groups of leader+worker inference replicas sit behind it, and the API is OpenAI-compatible."
      meta={<Text type="secondary">v1 · 2026-08-05</Text>}
    >
      <DocSection title="What It Is" subTitle="Concept" marginTop={0}>
        <UserBlock>
          An llm-d service has two parts:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              <b>Gateway</b>: a CPU-only routing layer and the single external entry point, which dispatches requests to the inference replica groups behind it
              (it supports cache-aware routing: with multiple replicas, requests go preferentially to the instances with higher hit rates)
            </li>
            <li>
              <b>Worker (inference replica groups)</b>: one or more groups of <b>leader + worker</b> nodes; each group does tensor parallelism / expert parallelism across machines,
              and together they serve one large model (you only need this for models that do not fit on one node)
            </li>
          </ul>
          <Paragraph style={{ marginTop: 10, marginBottom: 0 }}>
            Callers only know the single Gateway address and do not need to care how many replica groups there are or which machines they run on;
            requests are forwarded automatically to a suitable replica based on cache hits.
          </Paragraph>
        </UserBlock>
        <TechBlock>
          Gateway = sgl-model-gateway (CPU-only, stateless, can run multiple replicas for high availability).
          Worker = LeaderWorkerSet (LWS) CR; one group = 1 leader + (size-1) workers, gang-scheduled within the group,
          with distributed SGLang as the engine. The platform renders two sets of Deployment/Service resources: LWS + Gateway.
        </TechBlock>
      </DocSection>

      <DocSection title="When to Use It" subTitle="When to use">
        <UserBlock>
          <KeyValueList
            items={[
              {
                k: 'The model fits on one node',
                v: <>An <a href="/docs/inference">Inference Service</a> (single-node SGLang) is enough; it uses fewer resources and deploys faster</>,
              },
              {
                k: 'The model does not fit on one node and needs cross-node TP/EP',
                v: 'Choose llm-d, which groups nodes together to serve one large model',
              },
              {
                k: 'Multiple inference replica groups need to share one unified entry point (high concurrency, routing by cache hits)',
                v: "llm-d's Gateway natively supports multiple replica groups + cache-aware routing",
              },
            ]}
          />
        </UserBlock>
      </DocSection>

      <DocSection title="Create Form" subTitle="Create form">
        <Paragraph type="secondary" style={{ fontSize: 13 }}>
          A single page filled in section by section, split into "Basic info / Model source / Image / Instance (Worker) / Gateway configuration / Launch configuration / Advanced".
        </Paragraph>
        <KeyValueList
          items={[
            { k: 'Basic info', v: 'Display name (lowercase letters/digits/-, 3-21 characters; stricter than other task types because of the Kueue label length limit) + job name (generated automatically) + description + custom labels' },
            { k: 'Model source', v: 'FSx (choose an authorized mount source, mounted at /model in the container) or S3 (bucket + prefix; the mount point root is the model directory)' },
            { k: 'Image', v: 'SGLang engine image (Worker): the official SGLang image by default, or a custom ECR image' },
            {
              k: 'Instance (Worker)',
              v: 'Choose a GPU instance type + resource template (single-node spec) + replicas (how many independent leader+worker groups) + nodes per group (size, at least 2 machines for a cross-node group). Total GPUs = replicas × nodes × GPUs per Pod',
            },
            {
              k: 'Gateway configuration',
              v: 'Choose its instance type separately (CPU-only routing, so you can pick a cheaper instance type than the Worker) + a CPU pool resource template + replicas (stateless; ≥2 recommended for high availability) + extra routing arguments (advanced, optional)',
            },
            { k: 'Launch configuration', v: 'The SGLang launch command (one shared by leader and workers); it must include --model-path and --tp-size/--ep-size. The platform pre-fills the placeholder variables needed for multi-node networking; just keep them' },
            { k: 'Advanced', v: 'Rendered preview (before submitting, you can see the YAML actually generated by the backend)' },
          ]}
        />
      </DocSection>

      <DocSection title="How to Invoke" subTitle="Access">
        <UserBlock>
          Once the service is up, send all requests to the single <b>Gateway</b> address; the Gateway forwards them to one of the available inference replica groups:
          <pre style={{ background: '#f5f5f5', padding: 10, borderRadius: 6, fontSize: 12, marginTop: 8, marginBottom: 0 }}>
{`curl -s http://<job-name>-gateway.<namespace>.svc.cluster.local:30000/v1/models
curl -s http://<job-name>-gateway.<namespace>.svc.cluster.local:30000/v1/chat/completions \\
  -H 'Content-Type: application/json' \\
  -d '{"model":"<value of --served-model-name in your launch script>","messages":[...]}'`}
          </pre>
          <div style={{ marginTop: 8 }}>
            Currently it can only be invoked <b>from inside the cluster</b> (curl from a dev instance / training container in the same Workspace); public or VPC-internal exposure is not supported yet.
            The "Overview" tab on the details page shows this address so you can copy it directly.
          </div>
        </UserBlock>
      </DocSection>

      <DocSection title="Reading the Status" subTitle="Status">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li><b>Initializing → Pending deployment → Running</b>: the normal creation flow; once Running, the service can be invoked</li>
            <li><b>Failed</b>: something went wrong in rendering or scheduling; check the "Logs" tab on the details page to troubleshoot</li>
            <li><b>Stopped</b>: the state after a manual stop; the configuration is kept and can be cloned to rebuild, but the service is no longer reachable</li>
          </ul>
          <Paragraph style={{ marginTop: 10, marginBottom: 0 }}>
            The Pod cards in the "Overview" tab of the details page are grouped by <b>replica group</b> (one card per group, plus a separate one for the Gateway),
            making it easy to pinpoint which group and which machine has the problem.
          </Paragraph>
        </UserBlock>
      </DocSection>

      <DocSection title="Stop / Delete" subTitle="Lifecycle">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li><b>Stop</b>: releases the compute it occupies and keeps the full configuration; later you can choose "Clone config" to rebuild the same service directly from the create page</li>
            <li><b>Delete</b>: deletes the configuration too; this cannot be undone</li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="Logs / Monitoring" subTitle="Logs & Metrics">
        <UserBlock>
          The details page has three tabs:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li><b>Monitoring</b>: basic resource metrics such as GPU / CPU / memory / network, covering every Pod of the Worker and the Gateway</li>
            <li><b>SGLang Performance</b>: inference-engine-specific metrics: throughput / time to first token / KV cache hit rate / queued concurrency</li>
            <li>
              <b>Logs</b>: split into "Pod logs" (pick a specific Pod to view its live/historical output) and "Task logs" (search keywords across all Pods at once);
              usage is the same as for other task types; for details, see <a href="/docs/observability">Observability</a>
            </li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="Not Yet Implemented" subTitle="Not yet">
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>External exposure (VPC-internal ALB / public internet); currently only the in-cluster address can be called</li>
            <li>Inference engines other than SGLang</li>
            <li>Elastic scaling of Worker replicas (currently you have to change the configuration and rebuild manually)</li>
          </ul>
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
