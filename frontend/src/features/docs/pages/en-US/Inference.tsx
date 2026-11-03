import { Typography } from 'antd';
import DocPage, {
  DocSection,
  KeyValueList,
  TechBlock,
  UserBlock,
} from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsInference() {
  return (
    <DocPage
      title="Inference Service · Docs"
      description="Deploy a model as an OpenAI-compatible API: single-node SGLang engine, models loaded from FSx/S3, and three ways to invoke it (in-cluster / VPC ALB / public internet). Large models that do not fit on one node use multi-node inference (llm-d) instead."
      meta={<Text type="secondary">v4.1 · 2026-08-05</Text>}
    >
      <DocSection title="What It Is" subTitle="Concept" marginTop={0}>
        <UserBlock>
          An inference service = one <code>InferenceEndpointConfig</code> (IEC) → rendered by the operator into a set of Pods.
          Each Pod has 3 containers: the main SGLang engine + reverse-proxy + otel-collector.
          Clients call the OpenAI-style <code>/v1/chat/completions</code>. The details page shows the status, logs, and monitoring of each of the 3 containers.
          <br />
          <b>For large models that do not fit on one node (72B+ / full-parameter DeepSeek), see <a href="/docs/llmd">llm-d Inference</a></b>:
          this service uses multiple GPUs within a single Pod, while llm-d spans multiple Pods across nodes.
        </UserBlock>
        <TechBlock>
          The underlying CRD is the HyperPod-native <code>InferenceEndpointConfig</code>; the operator (officially maintained by SageMaker)
          renders it into a Deployment. What the platform does: form wrapper + CR rendering + three levels of exposure + SGLang monitoring.
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>Engine: <b>single-node SGLang</b> (multiple GPUs in one Pod, Framework locked to sglang); multi-node / large models go to the <a href="/docs/llmd">llm-d</a> branch</li>
            <li>Default image lmsysorg/sglang:latest; you can enter a custom ECR image (Image Hub can build one online)</li>
            <li>3 containers per Pod: sglang (main) + sidecar-reverse-proxy + otel-collector</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="Create Form" subTitle="Create form">
        <Paragraph type="secondary" style={{ fontSize: 13 }}>
          A single page filled in section by section. Each section maps to part of the IEC CR.
        </Paragraph>
        <KeyValueList
          items={[
            { k: 'Basic info', v: 'Display name + job name (derived from the display name) + description + custom labels' },
            { k: 'Model source', v: 'FSx (mounted at mount_path) or S3 (prefetched by the operator). Mount point = the mount_path of the selected FSx; write the model subpath in --model-path of the launch script' },
            { k: 'Image', v: 'Default lmsysorg/sglang:latest or a custom ECR image' },
            { k: 'Compute resources', v: 'Choose a resource pool + resource template → fills in the instance type/GPU/CPU/memory (for inference req=lim, controlled centrally by templates). Replicas + container port' },
            { k: 'Launch configuration', v: 'The SGLang launch_server command (edited in Monaco). It must include --model-path pointing to the model' },
            { k: 'Advanced', v: 'metrics switch (SGLang /metrics + DCGM) · public endpoint switch (off by default)' },
          ]}
        />
      </DocSection>

      <DocSection title="Three Ways to Invoke" subTitle="Access">
        <UserBlock>
          The "Invocation commands" card on the details page has three tabs; pick one based on where you call from:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li><b>In-Cluster (via a Workspace Dev Instance)</b>: connects directly to the ClusterIP routing-service (dev instance/Space)</li>
            <li><b>Inside the VPC (via ALB)</b>: an internal ALB (HTTPS with a self-signed certificate), reachable within the same VPC, /v1/chat/completions only</li>
            <li><b>Public Internet (via SageMaker Endpoint)</b>: requires turning on "Create SageMaker endpoint (public access)" at creation (SigV4 authentication)</li>
          </ul>
          Each tab provides curl / CLI examples.
        </UserBlock>
        <TechBlock>
          Three levels of exposure:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>ClusterIP routing-service:443 (plain HTTP): in-cluster</li>
            <li>Internal ALB (HTTPS, self-signed, 443): always created, decoupled from endpointName</li>
            <li>SageMaker endpoint: controlled by the <code>public_endpoint</code> switch (off by default). Off = the operator does not create it,
              saving 1 SageMaker ENI + instance charges; only ClusterIP/ALB are reachable</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="Service Status" subTitle="Status">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            The list and details pages show <b>two kinds of status</b> with different meanings. For details, see the "Status guide" tip that expands from the ? icon on the list page:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li>
              <b>Task status</b> (CR phase, from
              deploymentObjectOverallState): <code>DeploymentPending → DeploymentInProgress → DeploymentComplete (running)</code>;
              on failure <code>DeploymentFailed</code>;
              deletion flow <code>DeletionPending → DeletionInProgress → DeletionComplete</code> (on failure <code>DeletionFailed</code>);
              stopped by the user <code>Stopped</code> (a business sentinel state: the Pods/ALB/endpoint are destroyed but the CR is kept);
              fully deleted <code>Deleted</code>
            </li>
            <li>
              <b>Queue status</b> (Kueue's six states): <code>Queued / QuotaReserved / Admitted / PodsReady / Evicted / Finished</code>
            </li>
            <li>
              The list page has two independent filters, by task status and by queue status, and the chips show counts
            </li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="Pod and Container Status" subTitle="Pod status">
        <UserBlock>
          The Pod table on the details page shows READY (e.g. 3/3) / status / restarts / exit reason.
          Expand a Pod row to see the status of each of the 3 containers: the main sglang runs the model, reverse-proxy forwards requests, and otel-collector collects metrics.
          When something crashes, the reason column shows the real cause (e.g. an NVML error from a CUDA image landing on a CPU node, Evicted due to low disk, a wrong model path, and so on).
        </UserBlock>
        <TechBlock>
          Pod/container status is fetched from k8s in real time when the details page syncs (READY/STATUS/RESTARTS + the exit reason from lastState/state.terminated).
          ready=3/3 means all 3 containers in the Pod are ready. When metrics is off there is no otel-collector, so the container count changes.
        </TechBlock>
      </DocSection>

      <DocSection title="Monitoring" subTitle="Metrics">
        <UserBlock>
          The Monitoring tab on the details page: general GPU/CPU/GPU memory/network + SGLang-specific performance (throughput / cache hit rate / queue / KV usage).
        </UserBlock>
        <TechBlock>
          <KeyValueList
            items={[
              { k: 'General metrics', v: 'DCGM (GPU) + cAdvisor (CPU/memory), filtered by Pod' },
              { k: 'SGLang metrics', v: 'Built into the SGLang /metrics endpoint (when the metrics switch is on), collected by otel-collector' },
              { k: 'Data source', v: 'AMP (Amazon Managed Prometheus), fetched with SigV4' },
              { k: 'Frontend', v: 'Rendered in-house with ECharts (Plan B; an AMG iframe was ruled out early as blocked)' },
            ]}
          />
        </TechBlock>
      </DocSection>

      <DocSection title="Not Yet Implemented" subTitle="Not yet">
        <TechBlock>
          The following are on the roadmap but <b>not implemented yet</b>; the docs label them accordingly:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>Canary releases / traffic shifting with Argo Rollouts (planned)</li>
            <li>HPA/KEDA autoscaling (the schema reserves routing_strategy / l2_kv_cache fields, but there is no scaling logic)</li>
            <li>Multiple single-node engines such as vLLM / TensorRT-LLM (single-node is currently locked to SGLang; the multi-node llm-d branch already covers large models)</li>
          </ul>
          The replica count stays fixed at the value entered at creation and does not scale automatically.
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
