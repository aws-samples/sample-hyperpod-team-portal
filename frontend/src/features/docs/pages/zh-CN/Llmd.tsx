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
      title="llm-d 推理 · 文档"
      description="单机装不下的大模型跨节点部署 — 一个网关 (Gateway) 前面挡, 后面挂多组 leader+worker 推理副本, 兼容 OpenAI API。"
      meta={<Text type="secondary">v1 · 2026-08-05</Text>}
    >
      <DocSection title="它是什么" subTitle="Concept" marginTop={0}>
        <UserBlock>
          一个 llm-d 服务由两部分组成:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              <b>Gateway (网关)</b> — 纯 CPU 路由层, 对外统一入口, 负责把请求分发到下面的推理副本组
              (支持缓存感知路由, 多副本时优先转发给命中率高的实例)
            </li>
            <li>
              <b>Worker (推理副本组)</b> — 一组或多组 <b>leader + worker</b> 节点, 每组跨机做张量并行 / 专家并行,
              合起来撑一个大模型 (单机装不下的模型才需要这个)
            </li>
          </ul>
          <Paragraph style={{ marginTop: 10, marginBottom: 0 }}>
            调用方只认 Gateway 一个地址, 不用关心后面有几组副本、副本在哪台机器上,
            请求会按缓存命中情况自动转发给合适的副本。
          </Paragraph>
        </UserBlock>
        <TechBlock>
          Gateway = sgl-model-gateway (纯 CPU, 无状态, 可多副本高可用)。
          Worker = LeaderWorkerSet (LWS) CR, 一组 = 1 leader + (size-1) worker, 组内 gang 调度,
          引擎为 SGLang 分布式。平台渲染 LWS + Gateway 两组 Deployment/Service 资源。
        </TechBlock>
      </DocSection>

      <DocSection title="什么时候选它" subTitle="When to use">
        <UserBlock>
          <KeyValueList
            items={[
              {
                k: '模型单机能装下',
                v: <>用 <a href="/docs/inference">推理服务</a> (单机 SGLang) 就够, 更省资源、部署更快</>,
              },
              {
                k: '模型单机装不下, 要跨机 TP/EP',
                v: '选 llm-d, 跨节点组一张大模型',
              },
              {
                k: '要多组推理副本共享一个统一入口 (高并发、按缓存命中路由)',
                v: 'llm-d 的 Gateway 天生支持多副本组 + 缓存感知路由',
              },
            ]}
          />
        </UserBlock>
      </DocSection>

      <DocSection title="创建表单" subTitle="Create form">
        <Paragraph type="secondary" style={{ fontSize: 13 }}>
          单页分段填写, 分"基本信息 / 模型来源 / 镜像 / 实例 (Worker) / Gateway 配置 / 启动脚本 / 高级"几段。
        </Paragraph>
        <KeyValueList
          items={[
            { k: '基本信息', v: '显示名 (小写字母/数字/-, 3-21 位, 因 Kueue 标签长度限制比其他任务类型更紧) + 任务名 (自动生成) + 描述 + 自定义 label' },
            { k: '模型来源', v: 'FSx (选授权挂载源, 挂到容器 /model) 或 S3 (bucket + prefix, 挂载点根即模型目录)' },
            { k: '镜像', v: 'SGLang 引擎镜像 (Worker) — 默认官方 SGLang 镜像, 可填 ECR 自定义' },
            {
              k: '实例 (Worker)',
              v: '选 GPU 机型 + 资源模板 (单节点规格) + 副本数 (replicas, 几组独立 leader+worker) + 每组节点数 (size, 最少 2 机跨节点组网)。总 GPU = 副本 × 节点 × 单 Pod GPU',
            },
            {
              k: 'Gateway 配置',
              v: '独立选机型 (纯 CPU 路由, 可选比 Worker 更便宜的机型) + CPU 池资源模板 + 副本数 (无状态, 建议 ≥2 高可用) + 额外路由参数 (高级, 选填)',
            },
            { k: '启动脚本', v: 'SGLang 启动命令 (leader/worker 共用一份), 需含 --model-path 与 --tp-size/--ep-size; 平台已预填多机组网所需的占位变量, 保留即可' },
            { k: '高级', v: '渲染预览 (提交前可看后端真实生成的 YAML)' },
          ]}
        />
      </DocSection>

      <DocSection title="怎么调用" subTitle="Access">
        <UserBlock>
          服务起来后, 所有请求都发给<b>网关</b>这一个地址, 网关自己转发到某一组可用的推理副本上:
          <pre style={{ background: '#f5f5f5', padding: 10, borderRadius: 6, fontSize: 12, marginTop: 8, marginBottom: 0 }}>
{`curl -s http://<任务名>-gateway.<命名空间>.svc.cluster.local:30000/v1/models
curl -s http://<任务名>-gateway.<命名空间>.svc.cluster.local:30000/v1/chat/completions \\
  -H 'Content-Type: application/json' \\
  -d '{"model":"<你启动脚本里 --served-model-name 填的值>","messages":[...]}'`}
          </pre>
          <div style={{ marginTop: 8 }}>
            当前只能在<b>集群内部</b>调用 (从同工作空间的开发机 / 训练容器里 curl), 还不支持公网或 VPC 内网暴露。
            详情页"总览"tab 会展示这个地址, 可以直接复制。
          </div>
        </UserBlock>
      </DocSection>

      <DocSection title="状态怎么看" subTitle="Status">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li><b>初始化中 → 待部署 → 运行中</b> — 正常创建流程, 运行中即可调用</li>
            <li><b>已失败</b> — 渲染或调度出了问题, 看详情页"日志"tab 排查</li>
            <li><b>已停止</b> — 手动停止后的状态, 配置保留, 可以克隆重建, 但服务已不可访问</li>
          </ul>
          <Paragraph style={{ marginTop: 10, marginBottom: 0 }}>
            详情页"总览"tab 里的 Pod 卡片按<b>副本组</b>分开展示 (每组一张卡, Gateway 单独一张),
            方便定位是哪一组、哪一台机器出的问题。
          </Paragraph>
        </UserBlock>
      </DocSection>

      <DocSection title="停止 / 删除" subTitle="Lifecycle">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li><b>停止</b> — 释放算力占用, 保留全部配置, 之后可以在创建页选"克隆"直接重建同款服务</li>
            <li><b>删除</b> — 连配置一起删掉, 不可恢复</li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="日志 / 监控" subTitle="Logs & Metrics">
        <UserBlock>
          详情页有三个 tab:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li><b>监控</b> — GPU / CPU / 内存 / 网络等基础资源指标, 覆盖 Worker 和 Gateway 的每个 Pod</li>
            <li><b>SGLang 性能</b> — 推理引擎专属指标: 吞吐 / 首字延迟 / KV cache 命中率 / 排队并发</li>
            <li>
              <b>日志</b> — 分"Pod 日志"(选具体某个 Pod 看实时/历史输出) 与"任务日志"(跨全部 Pod 一起搜关键词),
              用法与其他任务类型一致, 详见 <a href="/docs/observability">可观测性</a>
            </li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="尚未实现" subTitle="Not yet">
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>对外暴露 (VPC 内 ALB / 公网), 当前只有集群内地址可调</li>
            <li>SGLang 之外的推理引擎</li>
            <li>Worker 副本数弹性伸缩 (当前需手动改配置重建)</li>
          </ul>
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
