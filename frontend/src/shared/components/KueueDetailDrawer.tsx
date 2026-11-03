/**
 * KueueDetailDrawer · 实时展示任务对应 Kueue Workload 的 conditions + admission。
 *
 * 数据来自后端 /{kind}/{id}/kueue-detail 实时端点 (不落库, 每次打开实时查)。
 * 三类资源各自传入 fetch 函数 (training/inference/devinstance 的 getXxxKueueDetail)。
 * conditions 为空 (任务已结束/未进 Kueue → Workload 已 GC) 时显示空提示。
 */
import { Alert, Badge, Drawer, Spin, Table, Typography } from 'antd';
import type { BadgeProps } from 'antd';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import type { KueueCondition, KueueDetail } from '@/shared/kueue';

interface Props {
  open: boolean;
  onClose: () => void;
  /** 实时拉取该任务的 Kueue 详情 (调用方按 kind 传入对应 client 函数)。 */
  fetcher: () => Promise<KueueDetail>;
  /** 抽屉宽度, 默认 760。 */
  width?: number | string;
  /** 是否显示遮罩 (默认 true)。传 false 则不遮挡、不阻塞背后页面点击。 */
  mask?: boolean;
}

function condStatusBadge(status?: string): BadgeProps['status'] {
  if (status === 'True') return 'success';
  if (status === 'False') return 'warning';
  return 'default';
}

const COLUMNS = [
  { title: 'Type', dataIndex: 'type', width: 120 },
  {
    title: 'Status',
    dataIndex: 'status',
    width: 90,
    render: (v: string | undefined) => <Badge status={condStatusBadge(v)} text={v ?? '-'} />,
  },
  { title: 'Reason', dataIndex: 'reason', width: 130 },
  { title: 'Message', dataIndex: 'message' },
  {
    title: 'LastTransition',
    dataIndex: 'lastTransitionTime',
    width: 96,
    // 变窄 + 换行: ISO 时间无空格不会自然折行, 手动拆成 date / time 两行。
    render: (v: string | undefined) => {
      if (!v) return '-';
      const [d, tm] = v.replace('Z', '').split('T');
      return (
        <span style={{ whiteSpace: 'normal', lineHeight: 1.3 }}>
          {d}
          {tm ? (
            <>
              <br />
              {tm}
            </>
          ) : null}
        </span>
      );
    },
  },
];

export default function KueueDetailDrawer({
  open,
  onClose,
  fetcher,
  width = 760,
  mask = true,
}: Props) {
  const { t } = useTranslation('common');
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<KueueDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setErr(null);
    fetcher()
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e) => {
        if (!cancelled) setErr(e?.message || t('messages.loadFailed'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // fetcher 每次渲染新建, 仅依赖 open 触发 (避免无限循环)。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const conditions: KueueCondition[] = detail?.conditions ?? [];
  const clusterQueue = (detail?.admission?.clusterQueue as string | undefined) ?? null;

  return (
    <Drawer title={t('kueueDetail.title')} width={width} mask={mask} open={open} onClose={onClose}>
      {loading ? (
        <Spin />
      ) : err ? (
        <Alert type="error" message={err} />
      ) : conditions.length === 0 ? (
        <Alert
          type="info"
          message={t('kueueDetail.emptyTitle')}
          description={t('kueueDetail.emptyDesc')}
        />
      ) : (
        <>
          {clusterQueue && (
            <Typography.Paragraph>
              <Typography.Text type="secondary">ClusterQueue: </Typography.Text>
              <Typography.Text strong>{clusterQueue}</Typography.Text>
            </Typography.Paragraph>
          )}
          <Table<KueueCondition>
            size="small"
            rowKey={(r) => r.type ?? Math.random().toString()}
            columns={COLUMNS}
            dataSource={conditions}
            pagination={false}
          />
        </>
      )}
    </Drawer>
  );
}
