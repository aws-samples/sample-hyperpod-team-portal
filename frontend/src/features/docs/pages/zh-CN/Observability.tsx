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
      title="可观测性 · 文档"
      description="指标 + 日志都在 UI 内 — GPU/CPU 监控图表 + 实时/历史日志 + 全任务 Insights 搜索, 不用跳 CloudWatch 找数据。"
      meta={<Text type="secondary">v3.1 · 2026-08-05</Text>}
    >
      <DocSection title="它包含什么" subTitle="Pillars" marginTop={0}>
        <UserBlock>
          <KeyValueList
            items={[
              { k: '指标', v: 'GPU 利用率/显存/温度 + Pod CPU/内存/网络 + SGLang 推理性能 — 详情页监控 tab' },
              { k: '队列 / 配额', v: '监控菜单 → 队列 / 配额 (Kueue): 名义配额 / 可借 / 使用中 / 等待中 workload 一屏定位' },
              { k: '日志', v: '训练/推理/llm-d/开发机 stdout — 实时流 + 历史翻页 (可翻至几千行) + 跨 Pod 全任务搜索' },
              { k: 'Pod 状态', v: '详情页 Pod 表: READY/状态/重启/退出原因 (OOMKilled/Evicted/退出码)' },
            ]}
          />
        </UserBlock>
        <TechBlock>
          走 AWS Managed 服务 + 官方 exporter:
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>指标存储: Amazon Managed Prometheus (AMP), 后端 SigV4 拉取</li>
            <li>指标采集: dcgm-exporter (GPU) + cAdvisor (Pod 资源) + SGLang /metrics (推理)</li>
            <li>日志: 实时走 kubectl logs --follow (SSE); 历史走 CloudWatch Logs Insights</li>
            <li>前端图表: ECharts 自渲染 (Plan B; AMG iframe 早期判定 blocked)</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="指标" subTitle="Metrics">
        <UserBlock>
          训练/推理详情页有监控 tab, 三个维度看 GPU: job (整任务) / pod (每 Pod) / gpu_card (每张卡)。
          推理另有 SGLang 专属性能 (吞吐 / cache 命中率 / 队列 / KV 用量)。
        </UserBlock>
        <TechBlock>
          <KeyValueList
            items={[
              { k: 'GPU 指标', v: 'DCGM-Exporter — 卡级 利用率/显存/SM/温度/功耗/ECC' },
              { k: 'Pod 指标', v: 'cAdvisor — CPU/内存/磁盘/网络/重启/退出事件' },
              { k: 'SGLang 指标', v: 'SGLang /metrics 端点 (metrics 开关开时), otel-collector 采集' },
              {
                k: 'pod 维度过滤',
                v: 'GPU 指标按 namespace+pod 过滤, 不按节点 — 碎片调度下利用率不被同节点别任务的卡稀释 (实测 25%→100%)',
              },
              { k: '查询路径', v: 'Frontend → 后端 → AMP Query API (SigV4 签名)' },
            ]}
          />
        </TechBlock>
      </DocSection>

      <DocSection title="日志" subTitle="Logs">
        <UserBlock>
          每个任务详情页有"日志"Tab, 三种模式按需切:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li><b>实时流</b> — 运行中 Pod 直连 stdout (SSE), 近 0 延迟</li>
            <li><b>历史翻页</b> — 单 Pod stream 分页浏览, 支持时间窗定位 + 关键词过滤 (CloudWatch)</li>
            <li><b>全任务搜索</b> — 跨该任务所有 Pod stream 一起 grep, Logs Insights 支撑</li>
          </ul>
          支持任务类型: 训练 / 推理 / llm-d (多机推理, leader/worker 分组) / 开发机。
          训练详情页还能点 Pod 进交互终端 调试。
          任务结束后 stream 列表缓存进 DDB, 后续零 CW ListStreams 命中。
        </UserBlock>
        <TechBlock>
          三条取数线 (都在 <code>services/platform-api/app/modules/logs/</code>):
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              <b>实时</b>: <code>GET /&lt;kind&gt;/&#123;id&#125;/logs/stream</code> — kubectl logs --follow 包成 SSE, 仅 Pod 活时用。
              训练/推理/llm-d 分别 fan out 到自己的 Pod label selector
            </li>
            <li>
              <b>历史翻页</b>: <code>GET /&lt;kind&gt;/&#123;id&#125;/logs/history?stream=…&amp;cursor=…&amp;limit=…</code> —
              CloudWatch GetLogEvents 分页, 浏览默认首屏 500 / 翻页 500 (跨页累积到 <code>limit</code>, 突破 CloudWatch 单次 1 MB 上限;
              coding agent 一次性拉可传 <code>limit≤10000</code>)。提供 <code>logs/history/download</code> 一次性拉全量做归档
            </li>
            <li>
              <b>全任务搜索</b>: <code>GET /&lt;kind&gt;/&#123;id&#125;/logs/search-all?filter=…&amp;from=&amp;to=</code> —
              Logs Insights 拼 filter_pattern 打全 stream, 返回结果按 pod/stream 分组
            </li>
            <li>
              去重: since_ms 游标对 Insights 不可靠 (查询窗口模糊), 客户端按 (ts+stream+pod+message) 去重
            </li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="尚未实现" subTitle="Not yet">
        <TechBlock>
          以下为规划方向, <b>当前未实现</b>:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>告警 (Alertmanager + SES/Slack + 预置规则) — 规划中, 当前无告警引擎</li>
            <li>
              日志冷层归档 — 冷备已落 (CloudWatch subscription → Firehose → S3 长期归档),
              但 UI 内查询仍走 CloudWatch, 尚未接 Athena 查询面板
            </li>
            <li>推理灰度 / 弹性扩缩相关指标面板</li>
          </ul>
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
