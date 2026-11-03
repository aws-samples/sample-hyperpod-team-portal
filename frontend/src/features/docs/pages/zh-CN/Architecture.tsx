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
      title="技术架构 · 文档"
      description="从前端 React 到 platform-controller 到 EKS 控制面到 SageMaker HyperPod 数据面 — 全貌, 每个请求经过哪些边界。"
      meta={<Text type="secondary">v3.2 · 2026-08-05</Text>}
    >
      <DocSection title="5 层全景" subTitle="System layers" marginTop={0}>
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} xl={8}>
            <LayerCard
              layer="L4 · Frontend"
              title="Web UI"
              items={[
                'Vite 5 + React 18 + TypeScript 5',
                'Ant Design 5 / ProComponents / ECharts 5',
                'Monaco 本地化 (生产 VPC CDN 不可用)',
              ]}
              accent="#0958d9"
            />
          </Col>
          <Col xs={24} sm={12} xl={8}>
            <LayerCard
              layer="L3 · Platform API"
              title="FastAPI 后端"
              items={[
                'Python 3.11 + FastAPI + aioboto3',
                '业务模块 (auth/workspace/cluster/quota/training/inference/llmd/devinstance/registry/secret/sharing/logs/...)',
                'Repository 层屏蔽 DDB schema',
                'DDB-only; 状态永远读 DDB, 不直接查 K8s',
                'OpenAPI 三合一: /api/docs (Swagger) · /api/redoc · /api/scalar',
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
                '监听 CR: HyperPodPyTorchJob / IEC / LWS(llm-d) / JupyterSpace + Pod',
                'derive/ · 状态派生 (Kueue 六态 + phase 拼接)',
                'ddb/writer · 幂等写回 ResourceIndex',
                'mapping/ + gvk/ · CR→资源类型统一映射',
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
                'amazon-sagemaker-spaces (开发机)',
                'HyperPod Training Operator (训练 · hyperpodrun)',
                'InferenceEndpointConfig operator (单机推理)',
                'KubeRay RayJob (Ray 分布式训练)',
                'LeaderWorkerSet + sgl-gateway (llm-d 多机推理)',
                'fsx-admin DaemonSet (lustre-client + lfs project quota)',
                'CodeBuild (镜像在线构建)',
                'Kyverno + ValidatingAdmissionPolicy (替代 Webhook)',
              ]}
              accent="#13c2c2"
            />
          </Col>
          <Col xs={24} sm={12} xl={8}>
            <LayerCard
              layer="L1 · Infra"
              title="HyperPod + EKS + 网络"
              items={[
                'SageMaker HyperPod 集群 (GPU + CPU 机型, 由管理员配置)',
                'HyperPod task governance ClusterSchedulerConfig (优先级档权威源)',
                'VPC 私有子网 + VPC Endpoints',
                'FSx Lustre (每 ws 挂一份, 子目录隔离 + lfs project 一级目录配额) + S3',
                'CloudWatch (FSx 指标 · Log Group + subscription → Firehose → S3 归档)',
                'EC2 DescribeInstanceTypes (机型规格权威源, TTL 缓存, us-east-1)',
              ]}
              accent="#52c41a"
            />
          </Col>
          <Col xs={24} sm={12} xl={8}>
            <LayerCard
              layer="L0 · Storage"
              title="DDB 单源"
              items={[
                'Workspaces / WorkspaceMembers / ResourceIndex',
                'ResourceTemplates / AuditLog / ApiTokens / PlatformAdmins',
                'ResourceShares (跨用户分享) · WorkspaceImages · ImageBuilds · Secrets',
                'Cognito UserPool (身份, 不在 DDB 复制 user 主数据)',
                'AWS API 实时拉取替代 RDS 缓存',
              ]}
              accent="#722ed1"
            />
          </Col>
          <Col xs={24} sm={12} xl={8}>
            <LayerCard
              layer="L1 · Observability"
              title="AMP + Plan B"
              items={[
                'Amazon Managed Prometheus (指标)',
                'dcgm-exporter (GPU) + cAdvisor (Pod)',
                'CloudWatch Logs (历史日志)',
                'ECharts 自渲染 (Plan B, AMG iframe blocked)',
              ]}
              accent="#fa8c16"
            />
          </Col>
        </Row>
      </DocSection>

      <DocSection title="一个请求的生命周期" subTitle="Request flow">
        <UserBlock>
          以"用户看训练任务列表"为例:
          <ol style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>浏览器加载 React 应用 → Cognito 拿 ID Token</li>
            <li>Bearer Token 携带 → 后端列表端点</li>
            <li>FastAPI 先 <code>assert_ws_member</code> (查 DDB WorkspaceMembers)</li>
            <li>读 DDB <code>ResourceIndex</code> 拿任务列表 (phase 已由 platform-controller 写入)</li>
            <li>详情页 <code>sync=true</code> 时再实时拉 K8s CR status / Pod</li>
            <li>合并 DDB metadata + K8s 实时状态 → 返回 JSON</li>
          </ol>
        </UserBlock>
        <TechBlock>
          <b>为什么 API 不直接查 K8s?</b> 独立 controller 服务 (Go 版, <code>services/platform-controller/</code>)
          用 informer 长连接监听 CR + Pod, 状态变了立刻派生 phase 写回 DDB.
          API 层保持无状态无长连, 只做 DDB 主键读 + 权限判定 —
          水平扩容自由, 冷启动零热身, 与前端跨端可替换 (CLI / SDK 共用).
          <br />
          详见 <code>services/platform-controller/internal/</code> 目录 — controller / derive / mapping / gvk / ddb.
        </TechBlock>
      </DocSection>

      <DocSection title="关键架构决策" subTitle="Architecture Decisions">
        <KeyValueList
          items={[
            {
              k: '工作空间',
              v: 'Workspace 复用 HyperPod team API (CreateComputeQuota 自动建 ns + queue)',
            },
            {
              k: '准入校验',
              v: 'Webhook 退化为 Kyverno + ValidatingAdmissionPolicy (CEL)',
            },
            {
              k: '开发机',
              v: 'DevInstance 不自研 Operator → informer + 兜底 cleanup',
            },
            {
              k: '数据存储',
              v: 'DDB 单数据源 (替代 Aurora + Redis)',
            },
            {
              k: '推理接入',
              v: '推理可选公网 SageMaker endpoint (默认关, 仅 ClusterIP/ALB)',
            },
            {
              k: 'GPU 监控',
              v: 'GPU 监控按 pod 过滤, 修碎片调度下利用率稀释',
            },
            {
              k: 'Token 中心',
              v: '个人 API Token / kv Secret 独立中心, 每人自管, 供 CLI/脚本免登',
            },
            {
              k: 'Ray 训练',
              v: 'Ray 训练走 KubeRay RayJob CR, 与 HyperPodPyTorchJob 平级',
            },
            {
              k: '多机推理',
              v: 'llm-d 多机推理 (LeaderWorkerSet + sgl-gateway), 与单机 IEC 独立 CRD',
            },
            {
              k: '优先级',
              v: '优先级档以 HyperPod task governance ClusterSchedulerConfig 为唯一权威源 (不再自建 WPC)',
            },
          ]}
        />
      </DocSection>

      <DocSection title="为什么 DDB 单源" subTitle="Why no SQL">
        <TechBlock>
          关系数据库在本场景的硬伤:
          <ol style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>min ACU 锁死 — 没流量也月烧固定成本, 跟按需 PaaS 成本承诺相悖</li>
            <li>数据形状是"几张元数据表 + K8s 实时拉取", 没有 JOIN 必要, 主键查询为主</li>
            <li>mutate 都能写成 conditional_check (CAS), 不需要 SQL 事务</li>
          </ol>
          DDB On-Demand + GSI + TTL 满足需求, RDS + Redis 已移除。
        </TechBlock>
      </DocSection>

      <DocSection title="部署形态" subTitle="Deployment">
        <KeyValueList
          items={[
            { k: '区域', v: '非中国区 (基线 us-west-2; 按实际部署调整)' },
            { k: '编排', v: 'CDK (infra) + 容器镜像 (platform-api / platform-controller / frontend)' },
            { k: '前端', v: 'Vite build 静态产物 → nginx 托管, ALB Ingress 路由' },
            { k: '远程访问', v: '实例在私有子网, 走 SSM Session Manager / 端口转发' },
          ]}
        />
      </DocSection>
    </DocPage>
  );
}
