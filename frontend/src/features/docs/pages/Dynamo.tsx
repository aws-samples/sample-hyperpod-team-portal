import { Typography } from 'antd';
import DocPage, {
  DocSection,
  KeyValueList,
  TechBlock,
  UserBlock,
} from '../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsDynamo() {
  return (
    <DocPage
      title="多机推理 · 文档"
      description="单机装不下的大模型 (72B+ / DeepSeek 全参) 跨节点部署 — Dynamo (Grove operator), 兼容 OpenAI API。"
      meta={<Text type="secondary">v1 · 2026-07-20</Text>}
    >
      <DocSection title="它是什么" subTitle="Concept" marginTop={0}>
        <UserBlock>
          一个多机推理 = 一个 <code>DynamoGraphDeployment</code> CR → Grove operator 编排 grove-frontend
          + 多个 worker Pod, 每 Pod 独占若干 GPU, 跨节点组一张大模型。
          调用还是 OpenAI 兼容 <code>/v1/chat/completions</code>, 但目标是内部 SVC <code>&lt;cr&gt;-frontend:8000</code>。
          <br />
          <br />
          什么时候用: 单机 8 卡装不下的模型 (72B 全精度需 &gt;144 GB), 或需要更高吞吐 / KV cache 拆分。
          单机能跑的走 <a href="/docs/inference">推理服务</a> 更省。
        </UserBlock>
        <TechBlock>
          底层 CRD 由 Grove operator 提供, 与单机 <code>InferenceEndpointConfig</code> 独立 —
          不共用后端模块、不共用列表、不共用暴露方式。
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>引擎: <b>SGLang 分布式</b> (dynamo.sglang), 单一 backend</li>
            <li>默认镜像 <code>nvcr.io/nvidia/ai-dynamo/sglang-runtime:1.2.1-efa-amd64</code>; EFA 已装</li>
            <li>拓扑: 1 × grove-frontend (聚合 + OpenAI 兼容) + N × worker (推理节点)</li>
            <li>状态派生: <code>services/platform-controller/internal/derive/derive_dynamo.go</code></li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="创建表单" subTitle="Create form">
        <Paragraph type="secondary" style={{ fontSize: 13 }}>
          单页分段填写。每段对应 CR 的一部分。表单代码在 <code>frontend/src/features/dynamo/components/CreateForm/</code>。
        </Paragraph>
        <KeyValueList
          items={[
            { k: '基础信息', v: '显示名 + 任务名 (显示名派生) + 描述 + 自定义 label' },
            { k: '模型来源', v: 'FSx (选授权挂载源 pvc) 或 S3 (bucket + prefix, prefetch 开关); 模型子路径写在启动脚本 --model-path' },
            { k: '镜像', v: '默认 dynamo-sglang runtime; 可填 ECR 自定义 (镜像中心可在线构建)' },
            { k: '实例', v: '资源模板 (机型 + 单节点 GPU/CPU/EFA) × node_count; 副本 = 1 (Dynamo 单副本多节点组一张模型)' },
            { k: '启动脚本', v: 'dynamo.sglang 启动命令 (Monaco), 需含 --model-path / --tp / --served-model-name' },
            { k: '高级', v: 'metrics 开关 · 自定义 label' },
          ]}
        />
      </DocSection>

      <DocSection title="调用方式" subTitle="Access">
        <UserBlock>
          最小切片<b>只有集群内 (grove-frontend SVC) 可达</b>, 从同 ws 开发机 curl:
          <pre style={{ background: '#f5f5f5', padding: 10, borderRadius: 6, fontSize: 12, marginTop: 8, marginBottom: 0 }}>
{`curl -s http://<cr名>-frontend.<ns>.svc.cluster.local:8000/v1/models
curl -s http://<cr名>-frontend.<ns>.svc.cluster.local:8000/v1/chat/completions \\
  -H 'Content-Type: application/json' \\
  -d '{"model":"<served-model-name>","messages":[...]}'`}
          </pre>
          <div style={{ marginTop: 8 }}>
            <b>model 值</b> = 启动脚本里的 <code>--served-model-name</code> (详情不单存, 用你脚本里的值)。
          </div>
          <div style={{ marginTop: 8 }}>
            对外 (VPC 内 ALB) 暴露为后续能力, 就绪后详情页"调用指令"卡会直接给真实地址。
          </div>
        </UserBlock>
        <TechBlock>
          Grove operator 建 SVC <code>&lt;cr&gt;-frontend</code> (ClusterIP :8000, OpenAI 兼容);
          worker SVC 内部通信, 不对外。SGLang <code>--served-model-name</code> 作 model 值,
          单模型不严格校验 model 名。
        </TechBlock>
      </DocSection>

      <DocSection title="状态" subTitle="Status">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            列表 / 详情有<b>两类状态</b>:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li>
              <b>任务状态</b> (CR <code>status.state</code>):
              <code>initializing → pending → successful (运行中)</code>;
              失败 <code>failed</code>; 主动停 <code>Stopped</code> (平台哨兵态, Pod 已回收 CR 保留)
            </li>
            <li>
              <b>排队状态</b> (Kueue 六态): <code>Queued / QuotaReserved / Admitted / PodsReady / Evicted / Finished</code>
            </li>
          </ul>
        </UserBlock>
        <TechBlock>
          controller informer 监听 DynamoGraphDeployment + 关联 Pod,
          derive_dynamo 派生 phase 写回 DDB <code>ResourceIndex</code>。
          Kueue Workload 通过 grove-frontend Pod uid 2 跳定位, <code>?sync=true</code> 时实时拉。
        </TechBlock>
      </DocSection>

      <DocSection title="停止 / 删除" subTitle="Lifecycle">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li><b>停止</b> — 删 CR (Grove operator 级联回收 Pod), DDB 保留 phase=Stopped; 可保留日志 / 后续 clone 参数</li>
            <li><b>删除</b> — 级联删 CR + Pod, DDB 行走完 Deletion 流程后 GC</li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="日志 / 监控" subTitle="Logs & Metrics">
        <UserBlock>
          详情页有<b>日志</b>和<b>监控</b>两个 tab:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>日志 — 支持实时流 (SSE) · 历史翻页 · 跨 frontend + worker Pod 全任务搜索, 见 <a href="/docs/observability">可观测性</a></li>
            <li>监控 — 通用 GPU/CPU/网络 + Dynamo 专属性能面板</li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="尚未实现" subTitle="Not yet">
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>对外 VPC ALB / SageMaker Endpoint 暴露 (第二批, 只集群内可达)</li>
            <li>SGLang 之外的引擎 backend (Dynamo 支持 vLLM/TRT-LLM, 平台当前锁 sglang)</li>
            <li>HPA / 副本级弹性 (副本固定 1)</li>
          </ul>
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
