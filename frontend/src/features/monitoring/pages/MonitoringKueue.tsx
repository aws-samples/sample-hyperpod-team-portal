import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, Button, Space, Table, Tag, theme, Tooltip, Typography } from 'antd';
import { PageContainer } from '@ant-design/pro-components';
import { QuestionCircleOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import PageDescription from '@/shared/ui/PageDescription';
import { listKueueQueues, type KueueQueueRow } from '@/api/monitoring';
import type { TaskRow } from '@/features/tasks/api';
import WorkspaceKueueTasks, {
  kueueDetailFetcher,
} from '../components/WorkspaceKueueTasks';
import KueueDetailDrawer from '@/shared/components/KueueDetailDrawer';

const { Text } = Typography;

const REFRESH_MS = 30_000;

/** 表头 + 问号说明: hover 小灰问号出解释文案。 */
function headerWithTip(label: string, tip: string) {
  return (
    <Space size={4}>
      <span>{label}</span>
      <Tooltip title={tip}>
        <QuestionCircleOutlined
          style={{ color: '#999', fontSize: 12, cursor: 'help' }}
        />
      </Tooltip>
    </Space>
  );
}

export default function MonitoringKueue() {
  const { t } = useTranslation(['monitoring', 'common']);
  const [rows, setRows] = useState<KueueQueueRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // 点「无法准入」计数展开的工作空间行 (workspace_id), 支持多行同时展开。
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);
  // 点任务「Kueue 详情」选中的任务 (null = 右侧 conditions 抽屉关闭)。
  const [detailTask, setDetailTask] = useState<TaskRow | null>(null);
  const { token } = theme.useToken();

  const load = useCallback(async (silent = false) => {
    if (!silent) setRows(null);
    try {
      setRows(await listKueueQueues());
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(true), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  const toggleExpand = (id: string) =>
    setExpandedKeys((keys) =>
      keys.includes(id) ? keys.filter((k) => k !== id) : [...keys, id],
    );

  const columns: ColumnsType<KueueQueueRow> = [
    {
      title: t('pages.kueue.workspace'),
      dataIndex: 'workspace_name',
      key: 'workspace_name',
      width: 320,
      ellipsis: true,
      render: (v: string, row) => (
        <Space direction="vertical" size={0}>
          <Text strong>{v || '-'}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {row.cluster_queue}
          </Text>
        </Space>
      ),
    },
    {
      title: headerWithTip(t('pages.kueue.activeHeader'), t('pages.kueue.activeTip')),
      dataIndex: 'active',
      key: 'active',
      width: 220,
      align: 'right',
      sorter: (a, b) => a.active - b.active,
      render: (v: number) =>
        v > 0 ? <Tag color="processing">{v}</Tag> : <Text type="secondary">0</Text>,
    },
    {
      title: headerWithTip(
        t('pages.kueue.inadmissibleHeader'),
        t('pages.kueue.inadmissibleTip'),
      ),
      dataIndex: 'inadmissible',
      key: 'inadmissible',
      width: 240,
      align: 'right',
      sorter: (a, b) => a.inadmissible - b.inadmissible,
      render: (v: number, row) =>
        v > 0 ? (
          <Tooltip title={t('pages.kueue.expandTip')}>
            <a
              onClick={() => toggleExpand(row.workspace_id)}
              style={{
                color: token.colorWarning,
                textDecoration: 'underline',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {v}
            </a>
          </Tooltip>
        ) : (
          <Text type="secondary">0</Text>
        ),
    },
  ];

  const detailFetcher = detailTask ? kueueDetailFetcher(detailTask) : null;

  return (
    <PageContainer
      header={{ title: t('pages.kueue.title') }}
      extra={[
        <Button key="r" icon={<ReloadOutlined />} onClick={() => void load()}>
          {t('common:actions.refresh')}
        </Button>,
      ]}
    >
      <PageDescription>{t('pages.kueue.description')}</PageDescription>
      {err && (
        <Alert
          type="error"
          message={t('pages.kueue.loadFailed')}
          description={err}
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}
      {/* 限宽而非加占位列: 占位列会渲出一片空白单元格 */}
      <div style={{ maxWidth: 820 }}>
        <Table<KueueQueueRow>
          rowKey="workspace_id"
          loading={rows === null}
          dataSource={rows ?? []}
          columns={columns}
          pagination={false}
          size="middle"
          expandable={{
            // 无独立展开图标列: 唯一展开入口是点「排队中的Pod（Inadmissible）」数字。
            showExpandColumn: false,
            expandedRowKeys: expandedKeys,
            expandedRowRender: (row) => (
              <WorkspaceKueueTasks
                workspaceId={row.workspace_id}
                inadmissibleCount={row.inadmissible}
                onShowDetail={(task) => setDetailTask(task)}
              />
            ),
          }}
        />
      </div>

      {/* 点任务「Kueue 详情」: 从右侧划出抽屉显示该 Workload 的 conditions。
          窄一点 + 无遮罩 (mask=false): 不遮挡、不阻塞左侧表格的点击。 */}
      <KueueDetailDrawer
        open={detailTask !== null && detailFetcher !== null}
        onClose={() => setDetailTask(null)}
        fetcher={detailFetcher ?? (() => Promise.resolve({ conditions: [], admission: {} }))}
        width={520}
        mask={false}
      />
    </PageContainer>
  );
}
