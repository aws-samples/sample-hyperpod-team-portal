import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  PageContainer,
  ProDescriptions,
  StatisticCard,
} from '@ant-design/pro-components';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Dropdown,
  Modal,
  Popconfirm,
  Row,
  Segmented,
  Select,
  Space,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  ApiOutlined,
  CopyOutlined,
  DeleteOutlined,
  ExpandOutlined,
  ExportOutlined,
  ImportOutlined,
  MoreOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SendOutlined,
  StopOutlined,
} from '@ant-design/icons';
import Editor from '@monaco-editor/react';
import { useAppStore } from '@/store';
import StatusBadge from '@/shared/ui/StatusBadge';
import LLMKpiRow from '@/shared/ui/metrics/LLMKpiRow';
import LLMMetricsGrid from '@/shared/ui/metrics/LLMMetricsGrid';
import ResourceMetricsGrid from '@/shared/ui/metrics/ResourceMetricsGrid';
import type { Granularity } from '@/shared/ui/metrics/ResourceMetricsGrid';
import LogViewer from '@/shared/ui/metrics/LogViewer';
import { mockInferenceServices } from '@/mock/inferenceServices';
import { mockWorkspaces } from '@/mock/workspaces';

const TIME_RANGES = [
  { label: '5m', value: 5 },
  { label: '15m', value: 15 },
  { label: '1h', value: 60 },
  { label: '6h', value: 360 },
  { label: '1d', value: 1440 },
];

const DEFAULT_REQ_BODY = `{
  "model": "qwen2-72b-prod",
  "messages": [
    { "role": "system", "content": "你是一个有用的助手。" },
    { "role": "user", "content": "介绍一下 vLLM 的 PagedAttention。" }
  ],
  "temperature": 0.7,
  "max_tokens": 256,
  "stream": false
}`;

const MOCK_RESPONSE = `{
  "id": "chatcmpl-a1b2c3d4",
  "object": "chat.completion",
  "created": 1734567890,
  "model": "qwen2-72b-prod",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "PagedAttention 是 vLLM 团队提出的一种高效 KV Cache 管理技术。它借鉴了操作系统虚拟内存分页的思想，将原本连续的 KV Cache 划分为固定大小的 block。这样可以：\\n\\n1) 几乎消除内部碎片，内存利用率接近 96%。\\n2) 支持灵活的前缀共享（prefix caching），相同 system prompt 的请求可共用 block，显著降低多轮对话延迟。\\n3) 方便 copy-on-write，实现 beam search 等并行解码时的廉价分支。"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 42,
    "completion_tokens": 187,
    "total_tokens": 229
  },
  "vllm_metrics": {
    "ttft_ms": 132,
    "itl_avg_ms": 41,
    "total_ms": 1420
  }
}`;

export default function InferenceDetail() {
  const { wsId = '', id = '' } = useParams();
  const navigate = useNavigate();
  const monacoTheme = useAppStore((s) =>
    s.themeMode === 'dark' ? 'vs-dark' : 'vs',
  );

  const svc = useMemo(
    () => mockInferenceServices.find((s) => s.id === id),
    [id],
  );

  const [activeTab, setActiveTab] = useState<string>('llm');

  // LLM tab
  const [llmGranularity, setLlmGranularity] = useState<'service' | 'replica'>(
    'service',
  );
  const [llmTimeRange, setLlmTimeRange] = useState<number>(15);

  // Instance tab
  const [instanceLevel, setInstanceLevel] = useState<'service' | 'instance'>(
    'service',
  );
  const [instanceTimeRange, setInstanceTimeRange] = useState<number>(15);
  const [selectedReplica, setSelectedReplica] = useState<string>('replica-0');

  // Playground tab
  const [reqBody, setReqBody] = useState<string>(DEFAULT_REQ_BODY);
  const [respBody, setRespBody] = useState<string>('');
  const [sending, setSending] = useState(false);
  const [lastLatency, setLastLatency] = useState<{
    ttft: number;
    total: number;
    tokens: number;
  } | null>(null);

  // More-menu state.
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState('');

  if (!svc) {
    return (
      <PageContainer title="推理服务详情">
        <Alert type="error" message={`找不到服务 ${id}`} showIcon />
      </PageContainer>
    );
  }

  const replicaList = Array.from(
    { length: svc.replicas },
    (_, i) => `replica-${i}`,
  );

  const handleSendRequest = () => {
    setSending(true);
    setRespBody('');
    // Fake streaming: fill body + latency after a delay
    window.setTimeout(() => {
      setRespBody(MOCK_RESPONSE);
      setLastLatency({
        ttft: 132 + Math.floor(Math.random() * 40),
        total: 1420 + Math.floor(Math.random() * 200),
        tokens: 229,
      });
      setSending(false);
    }, 900);
  };

  // =============================================================== Overview
  const overviewTab = (
    <Row gutter={[16, 16]}>
      <Col span={24}>
        <Row gutter={16}>
          <Col xs={12} md={6}>
            <StatisticCard
              statistic={{
                title: '副本状态',
                value: `${svc.replicas}`,
                suffix: '/ 4',
                valueStyle: { color: '#52c41a' },
              }}
            />
          </Col>
          <Col xs={12} md={6}>
            <StatisticCard
              statistic={{
                title: 'GPU 分配',
                value: svc.gpuCount * svc.replicas,
                suffix: `x ${svc.gpuType}`,
                valueStyle: { color: '#1677ff' },
              }}
            />
          </Col>
          <Col xs={12} md={6}>
            <StatisticCard
              statistic={{
                title: '当前 QPS',
                value: svc.qps ?? 0,
                precision: 1,
                suffix: 'req/s',
                valueStyle: { color: '#722ed1' },
              }}
            />
          </Col>
          <Col xs={12} md={6}>
            <StatisticCard
              statistic={{
                title: 'TTFT p50',
                value: svc.ttftMs ?? 0,
                suffix: 'ms',
                valueStyle: { color: '#fa8c16' },
              }}
            />
          </Col>
        </Row>
      </Col>
      <Col span={24}>
        <ProDescriptions
          title="服务详情"
          column={2}
          dataSource={svc}
          columns={[
            { title: '服务 ID', dataIndex: 'id', copyable: true },
            { title: '服务名', dataIndex: 'name' },
            {
              title: '状态',
              dataIndex: 'status',
              render: (_, r) => <StatusBadge status={r.status} />,
            },
            {
              title: '推理框架',
              dataIndex: 'framework',
              render: (_, r) => (
                <Tag color="purple">{r.framework.toUpperCase()}</Tag>
              ),
            },
            { title: '模型', dataIndex: 'modelRef', span: 2, copyable: true },
            {
              title: 'GPU 配置',
              render: (_, r) =>
                `${r.replicas} 副本 × ${r.gpuCount}x ${r.gpuType}`,
            },
            { title: '副本数', dataIndex: 'replicas' },
            {
              title: '端点 URL',
              dataIndex: 'endpointUrl',
              copyable: true,
              span: 2,
            },
          ]}
        />
      </Col>
    </Row>
  );

  // =============================================================== LLM Tab
  const llmTab = (
    <div>
      <Space size="middle" wrap style={{ marginBottom: 16 }}>
        <Space size={4}>
          <span style={{ color: '#666', fontSize: 12 }}>粒度:</span>
          <Segmented
            size="middle"
            value={llmGranularity}
            onChange={(v) => setLlmGranularity(v as 'service' | 'replica')}
            options={[
              { label: 'Service', value: 'service' },
              { label: 'Replica', value: 'replica' },
            ]}
          />
        </Space>
        <Space size={4}>
          <span style={{ color: '#666', fontSize: 12 }}>时间:</span>
          <Segmented
            size="middle"
            value={llmTimeRange}
            onChange={(v) => setLlmTimeRange(Number(v))}
            options={TIME_RANGES.map((r) => ({
              label: r.label,
              value: r.value,
            }))}
          />
        </Space>
        <Button size="small" icon={<ReloadOutlined />}>
          刷新
        </Button>
        <Button size="small" icon={<ExpandOutlined />}>
          全屏
        </Button>
      </Space>

      <div style={{ marginBottom: 16 }}>
        <LLMKpiRow />
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="KV Cache 使用率稳定在 67%，建议观察；若持续 >90% 则扩副本。"
      />

      <LLMMetricsGrid
        replicas={llmGranularity === 'replica' ? replicaList : ['service']}
        timeRangeMinutes={llmTimeRange}
      />
    </div>
  );

  // =============================================================== Instance Tab
  const instanceTab = (
    <div>
      <Space size="middle" wrap style={{ marginBottom: 16 }}>
        <Space size={4}>
          <span style={{ color: '#666', fontSize: 12 }}>维度:</span>
          <Segmented
            size="middle"
            value={instanceLevel}
            onChange={(v) => setInstanceLevel(v as 'service' | 'instance')}
            options={[
              { label: 'Service 级', value: 'service' },
              { label: 'Instance 级', value: 'instance' },
            ]}
          />
        </Space>
        {instanceLevel === 'instance' && (
          <Space size={4}>
            <span style={{ color: '#666', fontSize: 12 }}>Replica:</span>
            <Select
              size="small"
              style={{ width: 140 }}
              value={selectedReplica}
              onChange={setSelectedReplica}
              options={replicaList.map((r) => ({ label: r, value: r }))}
            />
          </Space>
        )}
        <Space size={4}>
          <span style={{ color: '#666', fontSize: 12 }}>时间:</span>
          <Segmented
            size="middle"
            value={instanceTimeRange}
            onChange={(v) => setInstanceTimeRange(Number(v))}
            options={TIME_RANGES.slice(0, 4).map((r) => ({
              label: r.label,
              value: r.value,
            }))}
          />
        </Space>
      </Space>

      <ResourceMetricsGrid
        granularity={
          (instanceLevel === 'service' ? 'job' : 'pod') as Granularity
        }
        selectedPods={
          instanceLevel === 'instance' ? [selectedReplica] : []
        }
        selectedGpuKeys={[]}
        timeRangeMinutes={instanceTimeRange}
      />
    </div>
  );

  // =============================================================== Logs Tab
  const logsTab = <LogViewer ranks={[0, 1]} />;

  // =============================================================== Playground
  const playgroundTab = (
    <Row gutter={16}>
      <Col xs={24} lg={12}>
        <Card
          size="small"
          title={
            <Space>
              <ApiOutlined />
              <span>请求</span>
              <Tag color="blue">OpenAI Chat Completions</Tag>
            </Space>
          }
          extra={
            <Button
              type="primary"
              size="small"
              icon={<SendOutlined />}
              loading={sending}
              onClick={handleSendRequest}
            >
              发送
            </Button>
          }
          bodyStyle={{ padding: 0 }}
        >
          <Editor
            height="520px"
            defaultLanguage="json"
            value={reqBody}
            onChange={(v) => setReqBody(v ?? '')}
            options={{
              minimap: { enabled: false },
              fontSize: 12,
              scrollBeyondLastLine: false,
            }}
            theme={monacoTheme}
          />
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card
          size="small"
          title={
            <Space>
              <PlayCircleOutlined />
              <span>响应</span>
              {lastLatency && (
                <>
                  <Tag color="green">TTFT {lastLatency.ttft}ms</Tag>
                  <Tag color="blue">总耗时 {lastLatency.total}ms</Tag>
                  <Tag>{lastLatency.tokens} tokens</Tag>
                </>
              )}
            </Space>
          }
          bodyStyle={{ padding: 0 }}
        >
          <Editor
            height="520px"
            defaultLanguage="json"
            value={respBody || '// 点击"发送"测试端点'}
            options={{
              readOnly: true,
              minimap: { enabled: false },
              fontSize: 12,
              scrollBeyondLastLine: false,
            }}
            theme={monacoTheme}
          />
        </Card>
      </Col>
    </Row>
  );

  const copyToClipboard = async (text: string) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      message.success('已复制到剪贴板');
    } catch {
      message.error('复制失败，请手动选择');
    }
  };

  const buildMockYaml = () =>
    [
      'apiVersion: serving.hyperpod.aws/v1',
      'kind: InferenceService',
      'metadata:',
      `  name: ${svc.name}`,
      `  workspace: ${svc.workspaceId}`,
      'spec:',
      `  framework: ${svc.framework}`,
      `  modelRef: ${svc.modelRef}`,
      `  replicas: ${svc.replicas}`,
      `  gpuType: ${svc.gpuType}`,
      `  gpuCount: ${svc.gpuCount}`,
      `  endpoint: ${svc.endpointUrl}`,
    ].join('\n');

  const handleMoreMenu = async ({ key }: { key: string }) => {
    switch (key) {
      case 'clone':
        message.info('已带入原参数');
        navigate(`/workspaces/${wsId}/inference/new?clone=${svc.id}`);
        break;
      case 'export-yaml':
        await copyToClipboard(buildMockYaml());
        break;
      case 'export-json':
        await copyToClipboard(JSON.stringify(svc, null, 2));
        break;
      case 'import-yaml':
        setImportText('');
        setImportOpen(true);
        break;
    }
  };

  const extraButtons = [
    <Button key="scale" icon={<ExpandOutlined />}>
      扩缩容
    </Button>,
    <Button
      key="test"
      icon={<ApiOutlined />}
      onClick={() => setActiveTab('playground')}
    >
      端点测试
    </Button>,
    <Popconfirm
      key="stop"
      title="确认停止该推理服务?"
      onConfirm={() => message.success('停止指令已发送')}
    >
      <Button danger icon={<StopOutlined />}>
        停止
      </Button>
    </Popconfirm>,
    <Dropdown
      key="more"
      menu={{
        items: [
          { key: 'clone', label: '克隆任务', icon: <CopyOutlined /> },
          { key: 'export-yaml', label: '导出 YAML', icon: <ExportOutlined /> },
          { key: 'export-json', label: '导出 JSON' },
          { key: 'import-yaml', label: '导入 YAML 覆盖', icon: <ImportOutlined /> },
        ],
        onClick: handleMoreMenu,
      }}
    >
      <Button icon={<MoreOutlined />}>更多</Button>
    </Dropdown>,
    <Popconfirm
      key="del"
      title="确认删除该服务?"
      onConfirm={() => {
        message.success('已删除');
        navigate(`/workspaces/${wsId}/inference`);
      }}
    >
      <Button danger icon={<DeleteOutlined />}>
        删除
      </Button>
    </Popconfirm>,
  ];

  return (
    <PageContainer
      header={{
        title: (
          <Space>
            <span>{svc.name}</span>
            <StatusBadge status={svc.status} />
            <Badge
              count={`${svc.replicas} 副本`}
              style={{ backgroundColor: '#52c41a' }}
            />
          </Space>
        ),
        breadcrumb: {
          items: [
            {
              title: (
                <a onClick={() => navigate(`/workspaces/${wsId}`)}>
                  {mockWorkspaces.find((w) => w.id === wsId)?.displayName ?? '工作空间'}
                </a>
              ),
            },
            {
              title: (
                <a onClick={() => navigate(`/workspaces/${wsId}/inference`)}>推理服务</a>
              ),
            },
            { title: svc.name },
          ],
        },
        subTitle: (
          <Typography.Text copyable={{ text: svc.endpointUrl }} type="secondary">
            {svc.endpointUrl}
          </Typography.Text>
        ),
      }}
      extra={extraButtons}
    >
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          { key: 'overview', label: '概览', children: overviewTab },
          { key: 'llm', label: 'LLM 监控', children: llmTab },
          { key: 'instance', label: '实例监控', children: instanceTab },
          { key: 'logs', label: '日志', children: logsTab },
          { key: 'playground', label: '端点测试', children: playgroundTab },
        ]}
      />
      <Modal
        title="导入 YAML 覆盖"
        open={importOpen}
        width={720}
        onCancel={() => setImportOpen(false)}
        onOk={() => {
          setImportOpen(false);
          message.success('配置已导入');
        }}
        okText="导入并覆盖"
        cancelText="取消"
      >
        <div style={{ border: '1px solid #d9d9d9', borderRadius: 6 }}>
          <Editor
            height="360px"
            defaultLanguage="yaml"
            value={importText}
            onChange={(v) => setImportText(v ?? '')}
            options={{
              minimap: { enabled: false },
              fontSize: 12,
              scrollBeyondLastLine: false,
            }}
            theme={monacoTheme}
          />
        </div>
      </Modal>
    </PageContainer>
  );
}
