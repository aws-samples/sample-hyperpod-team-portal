/**
 * Admin > Nodes — 真实节点列表 (M1: 接 GET /clusters/{tag}/nodes).
 *
 * 数据 100% 来自 AWS ListClusterNodes + DescribeClusterNode (TTL 30s).
 * 不再使用 mock 数据.
 */
import { useEffect, useState } from 'react';
import { Alert, Badge, Button, Space, Table, Tag, Typography, message } from 'antd';
import { PageContainer, StatisticCard } from '@ant-design/pro-components';
import type { ColumnsType } from 'antd/es/table';
import { ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { listClusterNodes, listClusters, type ClusterNode } from '@/features/admin/api/cluster';

const { Text } = Typography;

const STATUS_META: Record<string, { status: 'success' | 'warning' | 'error' | 'default'; label: string }> = {
  Running: { status: 'success', label: '运行中' },
  Failure: { status: 'error', label: '故障' },
  Pending: { status: 'warning', label: '等待中' },
  ShuttingDown: { status: 'default', label: '关机中' },
  Stopped: { status: 'default', label: '已停止' },
};

export default function NodesPage() {
  const [tag, setTag] = useState<string>('');
  const [items, setItems] = useState<ClusterNode[]>([]);
  const [total, setTotal] = useState(0);
  const [healthy, setHealthy] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = async (clusterTag: string) => {
    setLoading(true);
    setError(null);
    try {
      const resp = await listClusterNodes(clusterTag);
      setItems(resp.items);
      setTotal(resp.total);
      setHealthy(resp.healthy);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      setItems([]);
      message.error(`加载节点失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    (async () => {
      try {
        const clusters = await listClusters();
        const first = clusters[0];
        if (!first) {
          setError('未发现可用集群');
          setLoading(false);
          return;
        }
        setTag(first.cluster_tag);
        await refresh(first.cluster_tag);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
        setLoading(false);
      }
    })();
  }, []);

  const columns: ColumnsType<ClusterNode> = [
    {
      title: '实例 ID',
      dataIndex: 'instance_id',
      width: 220,
      render: (v: string) => <Text code copyable={{ text: v }}>{v}</Text>,
    },
    {
      title: '实例规格',
      dataIndex: 'instance_type',
      width: 160,
      render: (v: string) => <Tag color="blue">{v}</Tag>,
    },
    {
      title: 'Instance Group',
      dataIndex: 'instance_group_name',
      width: 220,
    },
    {
      title: '可用区',
      dataIndex: 'az',
      width: 120,
      render: (v?: string | null) => v ?? <Text type="secondary">—</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 120,
      render: (v: string) => {
        const meta = STATUS_META[v] ?? { status: 'default' as const, label: v };
        return <Badge status={meta.status} text={meta.label} />;
      },
    },
    {
      title: '加入时间',
      dataIndex: 'created_at',
      width: 200,
      render: (v: string | null) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '—'),
    },
  ];

  return (
    <PageContainer
      header={{
        title: '节点管理',
        subTitle: `集群 ${tag || '...'} · 数据来源 AWS ListClusterNodes (30s 缓存)`,
        extra: [
          <Button
            key="refresh"
            icon={<ReloadOutlined />}
            onClick={() => tag && refresh(tag)}
            loading={loading}
          >
            刷新
          </Button>,
        ],
      }}
    >
      {error && (
        <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />
      )}
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Space size={16} wrap>
          <StatisticCard
            statistic={{
              title: '节点总数',
              value: total,
              valueStyle: { color: '#1677ff' },
            }}
          />
          <StatisticCard
            statistic={{
              title: '健康',
              value: healthy,
              valueStyle: { color: '#52c41a' },
            }}
          />
          <StatisticCard
            statistic={{
              title: '异常',
              value: total - healthy,
              valueStyle: { color: total - healthy > 0 ? '#ff4d4f' : undefined },
            }}
          />
        </Space>

        <Table<ClusterNode>
          columns={columns}
          dataSource={items}
          rowKey="instance_id"
          loading={loading}
          pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 个节点` }}
          size="middle"
          bordered
        />
      </Space>
    </PageContainer>
  );
}
