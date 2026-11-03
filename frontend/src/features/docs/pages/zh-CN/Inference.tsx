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
      title="推理服务 · 文档"
      description="把模型部署成 OpenAI 兼容 API — SGLang 单机引擎, FSx/S3 加载模型, 集群内 / VPC ALB / 公网三种调用方式。单机装不下的大模型另有多机推理 (llm-d)。"
      meta={<Text type="secondary">v4.1 · 2026-08-05</Text>}
    >
      <DocSection title="它是什么" subTitle="Concept" marginTop={0}>
        <UserBlock>
          一个推理服务 = 一个 <code>InferenceEndpointConfig</code> (IEC) → operator 渲成一组 Pod。
          每个 Pod 内 3 个容器: 主 SGLang 引擎 + reverse-proxy + otel-collector。
          客户端按 OpenAI <code>/v1/chat/completions</code> 调。详情页能看 3 容器各自状态、日志、监控。
          <br />
          <b>单机装不下的大模型 (72B+ / DeepSeek 全参) 请看 <a href="/docs/llmd">llm-d 推理</a></b> —
          这个服务是单 Pod 内多卡, llm-d 是跨节点多 Pod。
        </UserBlock>
        <TechBlock>
          底层 CRD 是 HyperPod 原生 <code>InferenceEndpointConfig</code>, operator (SageMaker 官方维护)
          渲成 Deployment。平台做的是: 表单包装 + CR 渲染 + 三层暴露 + SGLang 监控。
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>引擎: <b>SGLang 单机</b> (单 Pod 多卡, Framework 锁 sglang); 多机 / 大模型走 <a href="/docs/llmd">llm-d</a> 分支</li>
            <li>默认镜像 lmsysorg/sglang:latest, 可填 ECR 自定义 (镜像中心可在线构建)</li>
            <li>每 Pod 3 容器: sglang (主) + sidecar-reverse-proxy + otel-collector</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="创建表单" subTitle="Create form">
        <Paragraph type="secondary" style={{ fontSize: 13 }}>
          单页分段填写。每段对应 IEC CR 的一部分。
        </Paragraph>
        <KeyValueList
          items={[
            { k: '基础信息', v: '显示名 + 任务名 (跟随显示名派生) + 描述 + 自定义 label' },
            { k: '模型来源', v: 'FSx (挂 mount_path) 或 S3 (operator prefetch)。挂载点 = 选中 FSx 的 mount_path; 模型子路径写在启动脚本 --model-path' },
            { k: '镜像', v: '默认 lmsysorg/sglang:latest 或 ECR 自定义' },
            { k: '实例', v: '选资源池 + 资源模板 → 带出机型/GPU/CPU/内存 (推理 req=lim, 模板统一管控)。副本数 + 容器端口' },
            { k: '启动脚本', v: 'SGLang launch_server 启动命令 (Monaco 编辑)。需含 --model-path 指向模型' },
            { k: '高级', v: 'metrics 开关 (SGLang /metrics + DCGM) · 公网 endpoint 开关 (默认关)' },
          ]}
        />
      </DocSection>

      <DocSection title="三种调用方式" subTitle="Access">
        <UserBlock>
          详情页"调用指令"卡给三个 tab, 按你从哪调选:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li><b>集群内</b> (开发机/Space) — 直连 ClusterIP routing-service</li>
            <li><b>VPC ALB</b> — 内部 ALB (HTTPS 自签证书), 同 VPC 内可达, 仅 /v1/chat/completions</li>
            <li><b>公网 SageMaker Endpoint</b> — 需创建时开"公网 endpoint"开关 (SigV4 鉴权)</li>
          </ul>
          每个 tab 给 curl / CLI 样例。
        </UserBlock>
        <TechBlock>
          三层暴露:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>ClusterIP routing-service:443 (明文 HTTP) — 集群内</li>
            <li>内部 ALB (HTTPS 自签 443) — 总建, 与 endpointName 解耦</li>
            <li>SageMaker endpoint — <code>public_endpoint</code> 开关控制 (默认关)。关 = operator 不建,
              省 1 SageMaker ENI + 实例计费, 仅 ClusterIP/ALB 可达</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="服务状态" subTitle="Status">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            列表 / 详情有<b>两类状态</b>, 含义不同 — 详细见列表页 ? 图标展开的"状态说明"tip:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li>
              <b>任务状态</b> (CR phase, 来源 deploymentObjectOverallState):
              <code>DeploymentPending → DeploymentInProgress → DeploymentComplete (运行中)</code>;
              失败 <code>DeploymentFailed</code>;
              删除流程 <code>DeletionPending → DeletionInProgress → DeletionComplete</code> (失败 <code>DeletionFailed</code>);
              主动停 <code>Stopped</code> (业务哨兵态, Pod/ALB/endpoint 已销毁但 CR 保留);
              彻底删 <code>Deleted</code>
            </li>
            <li>
              <b>排队状态</b> (Kueue 六态): <code>Queued / QuotaReserved / Admitted / PodsReady / Evicted / Finished</code>
            </li>
            <li>
              列表页有两个独立 filter — 按任务状态和排队状态分别过滤, chip 带计数
            </li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="Pod 与容器状态" subTitle="Pod status">
        <UserBlock>
          详情页 Pod 表显 READY (如 3/3) / 状态 / 重启 / 退出原因。
          点开 Pod 行看 3 容器各自状态 — 主 sglang 跑模型, reverse-proxy 转发, otel-collector 采指标。
          崩溃时原因列显真因 (如 CUDA 镜像落 CPU 节点的 NVML 错、Evicted 磁盘不足、模型路径错等)。
        </UserBlock>
        <TechBlock>
          Pod/容器状态详情页 sync 实时拉 k8s (READY/STATUS/RESTARTS + lastState/state.terminated 退出原因)。
          ready=3/3 即 Pod 内 3 容器全就绪。metrics 关时无 otel-collector, 容器数会变。
        </TechBlock>
      </DocSection>

      <DocSection title="监控" subTitle="Metrics">
        <UserBlock>
          详情页监控 tab: 通用 GPU/CPU/显存/网络 + SGLang 专属性能 (吞吐 / cache 命中率 / 队列 / KV 用量)。
        </UserBlock>
        <TechBlock>
          <KeyValueList
            items={[
              { k: '通用指标', v: 'DCGM (GPU) + cAdvisor (CPU/内存), 按 pod 过滤' },
              { k: 'SGLang 指标', v: 'SGLang /metrics 端点自带 (metrics 开关开启时), otel-collector 采集' },
              { k: '数据源', v: 'AMP (Amazon Managed Prometheus), SigV4 拉取' },
              { k: '前端', v: 'ECharts 自渲染 (Plan B; AMG iframe 早期判定 blocked)' },
            ]}
          />
        </TechBlock>
      </DocSection>

      <DocSection title="尚未实现" subTitle="Not yet">
        <TechBlock>
          以下为规划方向, <b>当前未实现</b>, 文档据实标注:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>灰度发布 / Argo Rollouts 切流 (规划中)</li>
            <li>HPA/KEDA 自动弹性扩缩 (schema 留了 routing_strategy / l2_kv_cache 字段, 无扩缩逻辑)</li>
            <li>vLLM / TensorRT-LLM 单机多引擎 (当前单机锁 SGLang; 多机走 llm-d 分支已覆盖大模型)</li>
          </ul>
          副本数固定按创建时填的值, 不自动伸缩。
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
