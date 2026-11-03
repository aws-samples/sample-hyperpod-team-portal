/**
 * Admin > Audit — 真 DDB AuditLog 表 (M1).
 *
 * 端点 GET /admin/audit-logs?scope=global|ws#<id>&actor_user_id=<uid>
 */
import { useEffect, useMemo, useState } from 'react';
import { Alert, Badge, Button, Input, Segmented, Space, Table, Tag, Typography, message } from 'antd';
import { PageContainer, StatisticCard } from '@ant-design/pro-components';
import type { ColumnsType } from 'antd/es/table';
import { ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { apiFetch } from '@/shared/api';

const { Text } = Typography;

interface AuditLogItem {
  scope_key: string;
  event_key: string;
  event_id: string;
  created_at: string;
  actor_user_id: string;
  actor_role?: string;
  operation: string;
  target_type: string;
  target_id: string;
  status: string;
  reason?: string;
  aws_request_id?: string;
  expire_at?: string;
}

interface AuditLogResponse {
  total: number;
  items: AuditLogItem[];
}

const STATUS_META: Record<string, { color: 'success' | 'error' | 'processing' | 'default'; label: string }> = {
  success: { color: 'success', label: '成功' },
  failed: { color: 'error', label: '失败' },
  submitted: { color: 'processing', label: '已提交' },
  in_progress: { color: 'processing', label: '执行中' },
};

const OP_TAG_COLORS: Record<string, string> = {
  ws: 'blue',
  quota: 'gold',
  dev: 'cyan',
  training: 'purple',
  node: 'magenta',
  user: 'default',
};

function listAudit(scope: string): Promise<AuditLogResponse> {
  const params = new URLSearchParams();
  if (scope) params.set('scope', scope);
  return apiFetch<AuditLogResponse>(`/admin/audit-logs?${params.toString()}`);
}

export default function AuditPage() {
  const [scope, setScope] = useState<string>('global');
  const [items, setItems] = useState<AuditLogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [error, setError] = useState<string | null>(null);

  const refresh = async (s: string) => {
    setLoading(true);
    setError(null);
    try {
      const resp = await listAudit(s);
      setItems(resp.items);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      message.error(`加载审计日志失败: ${msg}`);
      setItems([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh(scope);
  }, [scope]);

  const filteredItems = useMemo(() => {
    if (!search) return items;
    const q = search.toLowerCase();
    return items.filter(
      (i) =>
        i.operation.toLowerCase().includes(q) ||
        (i.reason ?? '').toLowerCase().includes(q) ||
        i.target_id.toLowerCase().includes(q),
    );
  }, [items, search]);

  const stats = useMemo(() => {
    const today = items.filter((i) => dayjs(i.created_at).isAfter(dayjs().subtract(1, 'day'))).length;
    const failed = items.filter((i) => i.status === 'failed').length;
    const uniqueActors = new Set(items.map((i) => i.actor_user_id)).size;
    return { today, failed, uniqueActors };
  }, [items]);

  const columns: ColumnsType<AuditLogItem> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 180,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '操作人',
      dataIndex: 'actor_user_id',
      width: 220,
      render: (uid: string, row) => (
        <Space direction="vertical" size={0}>
          <Text code style={{ fontSize: 11 }}>{uid.slice(0, 8)}…</Text>
          {row.actor_role && <Tag color="default">{row.actor_role}</Tag>}
        </Space>
      ),
    },
    {
      title: '操作',
      dataIndex: 'operation',
      width: 200,
      render: (op: string) => {
        const prefix = op.split('.')[0];
        return <Tag color={OP_TAG_COLORS[prefix] ?? 'default'}>{op}</Tag>;
      },
    },
    {
      title: '资源类型',
      dataIndex: 'target_type',
      width: 130,
    },
    {
      title: '目标 ID',
      dataIndex: 'target_id',
      width: 220,
      ellipsis: true,
      render: (v: string) => <Text code>{v}</Text>,
    },
    {
      title: 'Scope',
      dataIndex: 'scope_key',
      width: 240,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => {
        const meta = STATUS_META[v] ?? { color: 'default' as const, label: v };
        return <Badge status={meta.color} text={meta.label} />;
      },
    },
    {
      title: '说明',
      dataIndex: 'reason',
      ellipsis: true,
      render: (v?: string) => v ?? '—',
    },
  ];

  return (
    <PageContainer
      header={{
        title: '操作审计',
        subTitle: '所有管理与业务操作的全量审计日志 · 数据来源 DDB AuditLog 表',
        extra: [
          <Button key="r" icon={<ReloadOutlined />} onClick={() => refresh(scope)} loading={loading}>
            刷新
          </Button>,
        ],
      }}
    >
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Space size={16} wrap>
          <StatisticCard statistic={{ title: '总计 (当前 scope)', value: items.length, valueStyle: { color: '#1677ff' } }} />
          <StatisticCard statistic={{ title: '今日操作', value: stats.today, valueStyle: { color: '#52c41a' } }} />
          <StatisticCard statistic={{ title: '失败操作', value: stats.failed, valueStyle: { color: stats.failed > 0 ? '#ff4d4f' : undefined } }} />
          <StatisticCard statistic={{ title: '唯一操作人', value: stats.uniqueActors, valueStyle: { color: '#722ed1' } }} />
        </Space>

        <Space size={12} wrap>
          <Segmented
            value={scope}
            onChange={(v) => setScope(v as string)}
            options={[
              { label: '全平台', value: 'global' },
              { label: 'NLP Team', value: 'ws#15e2a2ce-8152-4c3e-b4a9-832f9720cd68' },
            ]}
          />
          <Input.Search
            placeholder="搜索操作 / 目标 / 说明"
            allowClear
            style={{ width: 280 }}
            onChange={(e) => setSearch(e.target.value)}
          />
        </Space>

        <Table<AuditLogItem>
          columns={columns}
          dataSource={filteredItems}
          rowKey="event_id"
          loading={loading}
          size="middle"
          pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
          bordered
        />
      </Space>
    </PageContainer>
  );
}
