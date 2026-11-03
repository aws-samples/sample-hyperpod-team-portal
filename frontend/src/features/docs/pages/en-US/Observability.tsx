import { Typography } from 'antd';
import DocPage, {
  DocSection,
  KeyValueList,
  TechBlock,
  UserBlock,
} from '../../components/DocPage';

const { Text } = Typography;

export default function DocsObservability() {
  return (
    <DocPage
      title="Observability · Docs"
      description="Metrics and logs are all inside the UI: GPU/CPU monitoring charts + live/historical logs + Insights search across all task logs, so you don't have to jump to CloudWatch to find data."
      meta={<Text type="secondary">v3.1 · 2026-08-05</Text>}
    >
      <DocSection title="What It Includes" subTitle="Pillars" marginTop={0}>
        <UserBlock>
          <KeyValueList
            items={[
              { k: 'Metrics', v: 'GPU utilization/memory/temperature + Pod CPU/memory/network + SGLang inference performance, in the Monitoring tab of the details page' },
              { k: 'Queue / quota', v: 'Monitoring menu → Queue (Kueue): nominal quota / borrowable / in use / pending workloads, all on one screen' },
              { k: 'Logs', v: 'stdout of training/inference/llm-d/dev instances: live logs + log history (scrolls through thousands of lines) + cross-Pod search across all task logs' },
              { k: 'Pod status', v: 'The Pod table on the details page: READY/status/restarts/exit reason (OOMKilled/Evicted/exit code)' },
            ]}
          />
        </UserBlock>
        <TechBlock>
          Built on AWS managed services + official exporters:
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>Metric storage: Amazon Managed Prometheus (AMP), queried by the backend with SigV4</li>
            <li>Metric collection: dcgm-exporter (GPU) + cAdvisor (Pod resources) + SGLang /metrics (inference)</li>
            <li>Logs: live via kubectl logs --follow (SSE); history via CloudWatch Logs Insights</li>
            <li>Frontend charts: rendered in-house with ECharts (Plan B; the AMG iframe was ruled out as blocked early on)</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="Metrics" subTitle="Metrics">
        <UserBlock>
          The training/inference details pages have a Monitoring tab that shows GPUs along three dimensions: job (the whole task) / pod (per Pod) / gpu_card (per card).
          Inference also has SGLang-specific performance metrics (throughput / cache hit rate / queue / KV usage).
        </UserBlock>
        <TechBlock>
          <KeyValueList
            items={[
              { k: 'GPU metrics', v: 'DCGM-Exporter: per-card utilization/memory/SM/temperature/power/ECC' },
              { k: 'Pod metrics', v: 'cAdvisor: CPU/memory/disk/network/restarts/exit events' },
              { k: 'SGLang metrics', v: 'The SGLang /metrics endpoint (when the metrics switch is on), collected by otel-collector' },
              {
                k: 'Filtering by pod',
                v: "GPU metrics are filtered by namespace+pod, not by node, so under fragmented scheduling, utilization is not diluted by other tasks' GPUs on the same node (measured 25%→100%)",
              },
              { k: 'Query path', v: 'Frontend → backend → AMP Query API (SigV4-signed)' },
            ]}
          />
        </TechBlock>
      </DocSection>

      <DocSection title="Logs" subTitle="Logs">
        <UserBlock>
          Every task details page has a "Logs" tab with three modes you can switch between as needed:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li><b>Live logs</b>: connects directly to the stdout of running Pods (SSE), with near-zero latency</li>
            <li><b>Log history</b>: browse a single Pod stream page by page, with time-window positioning + keyword filtering (CloudWatch)</li>
            <li><b>Search all logs</b>: grep across all Pod streams of the task at once, backed by Logs Insights</li>
          </ul>
          Supported task types: training / inference / llm-d (multi-node inference, grouped into leader/worker) / dev instance.
          On the training details page you can also click a Pod to open an interactive terminal for debugging.
          After a task finishes, its stream list is cached in DDB, so later requests make zero CW ListStreams calls.
        </UserBlock>
        <TechBlock>
          Three data paths (all in <code>services/platform-api/app/modules/logs/</code>):
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              <b>Live</b>: <code>GET /&lt;kind&gt;/&#123;id&#125;/logs/stream</code> wraps kubectl logs --follow as SSE and is only used while the Pod is alive.
              Training/inference/llm-d each fan out to their own Pod label selector
            </li>
            <li>
              <b>Log history</b>: <code>GET /&lt;kind&gt;/&#123;id&#125;/logs/history?stream=…&amp;cursor=…&amp;limit=…</code> pages through
              CloudWatch GetLogEvents; browsing loads 500 lines for the first screen / 500 per page by default (accumulating across pages up to <code>limit</code>, which gets past CloudWatch's 1 MB per-call cap;
              a coding agent fetching everything at once can pass <code>limit≤10000</code>). <code>logs/history/download</code> is provided to fetch everything at once for archiving
            </li>
            <li>
              <b>Search all logs</b>: <code>GET /&lt;kind&gt;/&#123;id&#125;/logs/search-all?filter=…&amp;from=&amp;to=</code> builds a
              Logs Insights filter_pattern and runs it across all streams; results are grouped by pod/stream
            </li>
            <li>
              Deduplication: the since_ms cursor is unreliable for Insights (the query window is fuzzy), so the client deduplicates by (ts+stream+pod+message)
            </li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="Not Yet Implemented" subTitle="Not yet">
        <TechBlock>
          The following are planned directions and are <b>not implemented yet</b>:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>Alerting (Alertmanager + SES/Slack + preset rules): planned; there is currently no alerting engine</li>
            <li>
              Cold-tier log archiving: the cold backup is in place (CloudWatch subscription → Firehose → S3 long-term archive),
              but in-UI queries still go through CloudWatch, and an Athena query panel is not wired up yet
            </li>
            <li>Metric panels for inference canary rollouts / autoscaling</li>
          </ul>
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
