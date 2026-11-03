import { useMemo, useRef } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { Badge, Button, Space, Tag, Typography } from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { InferenceService } from '@/types';
import { mockInferenceServices } from '@/mock/inferenceServices';
import { mockWorkspaces } from '@/mock/workspaces';
import StatusBadge from '@/shared/ui/StatusBadge';

const FRAMEWORK_COLOR: Record<InferenceService['framework'], string> = {
  vllm: 'purple',
  sglang: 'cyan',
  trtllm: 'gold',
};

export default function InferenceList() {
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const actionRef = useRef<ActionType>();

  const wsServices = useMemo(
    () => mockInferenceServices.filter((s) => s.workspaceId === wsId),
    [wsId],
  );
  const workspaceName = useMemo(
    () => mockWorkspaces.find((w) => w.id === wsId)?.displayName ?? '工作空间',
    [wsId],
  );

  const columns: ProColumns<InferenceService>[] = [
    {
      title: '服务名',
      dataIndex: 'name',
      width: 220,
      copyable: true,
      render: (_, row) => (
        <Link to={`/workspaces/${wsId}/inference/${row.id}`}>{row.name}</Link>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      valueEnum: {
        serving: { text: '服务中', status: 'Success' },
        pending: { text: '待调度', status: 'Processing' },
        failed: { text: '已失败', status: 'Error' },
      },
      render: (_, row) => <StatusBadge status={row.status} />,
    },
    {
      title: '框架',
      dataIndex: 'framework',
      width: 100,
      valueEnum: {
        vllm: 'vLLM',
        sglang: 'SGLang',
        trtllm: 'TRT-LLM',
      },
      render: (_, row) => (
        <Tag color={FRAMEWORK_COLOR[row.framework]}>
          {row.framework.toUpperCase()}
        </Tag>
      ),
    },
    {
      title: '模型',
      dataIndex: 'modelRef',
      width: 280,
      ellipsis: true,
      copyable: true,
    },
    {
      title: 'GPU',
      width: 150,
      search: false,
      render: (_, row) => (
        <Tag color="blue">
          {row.gpuCount}x {row.gpuType}
        </Tag>
      ),
    },
    {
      title: '副本',
      dataIndex: 'replicas',
      width: 80,
      search: false,
      render: (_, row) => (
        <Badge count={row.replicas} color="green" showZero />
      ),
    },
    {
      title: 'QPS',
      dataIndex: 'qps',
      width: 90,
      search: false,
      render: (v) => (v != null ? Number(v).toFixed(1) : '-'),
    },
    {
      title: 'TTFT (ms)',
      dataIndex: 'ttftMs',
      width: 110,
      search: false,
      render: (v) => (v != null ? `${v}` : '-'),
    },
    {
      title: '端点',
      dataIndex: 'endpointUrl',
      ellipsis: true,
      render: (v) => (
        <Typography.Text copyable={{ text: v as string }} style={{ fontSize: 12 }}>
          {v}
        </Typography.Text>
      ),
    },
    {
      title: '操作',
      width: 180,
      search: false,
      fixed: 'right',
      render: (_, row) => (
        <Space>
          <a onClick={() => navigate(`/workspaces/${wsId}/inference/${row.id}`)}>
            详情
          </a>
          <a>扩缩容</a>
          <a style={{ color: '#f5222d' }}>停止</a>
        </Space>
      ),
    },
  ];

  return (
    <PageContainer
      header={{
        title: '推理服务',
        breadcrumb: {
          items: [
            { title: <a onClick={() => navigate(`/workspaces/${wsId}`)}>{workspaceName}</a> },
            { title: '推理服务' },
          ],
        },
      }}
      extra={[
        <Button
          key="refresh"
          icon={<ReloadOutlined />}
          onClick={() => actionRef.current?.reload()}
        >
          刷新
        </Button>,
        <Button
          key="new"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate(`/workspaces/${wsId}/inference/new`)}
        >
          新建推理服务
        </Button>,
      ]}
    >
      <ProTable<InferenceService>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        dataSource={wsServices}
        search={{ labelWidth: 'auto' }}
        pagination={{ pageSize: 10 }}
        scroll={{ x: 1400 }}
        toolBarRender={false}
        options={{ reload: false, setting: true, density: true, fullScreen: true }}
      />
    </PageContainer>
  );
}
