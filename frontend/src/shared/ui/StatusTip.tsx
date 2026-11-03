import { useState } from 'react';
import type { ReactNode } from 'react';
import { Alert, Badge, Tag } from 'antd';
import type { BadgeProps } from 'antd';
import { DownOutlined, UpOutlined } from '@ant-design/icons';
import { useTranslation, Trans } from 'react-i18next';
import { phaseColor, kueueStatusColor } from '@/shared/status';

/**
 * 任务列表页通用「状态码说明」tip。两段:
 *   1. 任务状态 (CR phase): 各模块自定义, 由 phaseRows 传入。
 *   2. 排队状态 (Kueue 六态): 跨模块统一, 内置在本组件。
 *
 * 默认收起, 右上角"展开/收起"; 与其它页 Alert tip 风格一致。
 */

export interface PhaseRow {
  /** CR phase 原值 (如 "Available", "DeploymentComplete") */
  value: string;
  /** 显示名 (如 "运行中" / "Running") */
  label: string;
  /** 一句话含义 + 背后原理 (跟用户讲清楚什么时候出现, 是谁写的态) */
  detail: ReactNode;
}

interface StatusTipProps {
  /** 业务侧 CR phase 列表 (开发机 / 训练 / 推理 各自不同) */
  phaseRows: PhaseRow[];
  /** Phase 来源说明 (eg. "SageMaker Spaces Workspace CR.status.phase") */
  phaseSource: string;
}

// Kueue 六态: 跨模块统一, 来源 = 后端 informer 把 Workload condition 镜像到 DDB,
// derive_kueue_status_from_workload (services/.../shared/kueue_status.py) 按固定优先级取最高的 True 态。
// 六态值本身原样显示不翻译; 说明文案存 key, 渲染时再 t()。
const KUEUE_ROW_KEYS = [
  { value: 'Queued', key: 'tip.kueue.queued' },
  { value: 'QuotaReserved', key: 'tip.kueue.quotaReserved' },
  { value: 'Admitted', key: 'tip.kueue.admitted' },
  { value: 'PodsReady', key: 'tip.kueue.podsReady' },
  { value: 'Evicted', key: 'tip.kueue.evicted' },
  { value: 'Finished', key: 'tip.kueue.finished' },
] as const;

function StatusTable({
  rows,
  badgeColor,
}: {
  rows: { value: string; label?: string; detail: ReactNode }[];
  badgeColor: (v: string) => BadgeProps['status'];
}) {
  return (
    <table
      style={{
        width: '100%',
        borderCollapse: 'collapse',
        fontSize: 13,
      }}
    >
      <tbody>
        {rows.map((r) => (
          <tr key={r.value}>
            <td
              style={{
                width: 200,
                padding: '6px 12px 6px 0',
                verticalAlign: 'top',
                whiteSpace: 'nowrap',
              }}
            >
              <Badge status={badgeColor(r.value)} />
              <Tag color="default" style={{ marginLeft: 4, fontFamily: 'monospace' }}>
                {r.value}
              </Tag>
              {r.label && (
                <span style={{ color: 'rgba(0,0,0,0.65)' }}>{r.label}</span>
              )}
            </td>
            <td style={{ padding: '6px 0', color: 'rgba(0,0,0,0.65)' }}>
              {r.detail}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function StatusTip({ phaseRows, phaseSource }: StatusTipProps) {
  const { t } = useTranslation(['status', 'common']);
  const [open, setOpen] = useState(false);
  const kueueRows = KUEUE_ROW_KEYS.map((r) => ({
    value: r.value,
    detail:
      r.value === 'Evicted' ? (
        <span>
          <Trans i18nKey="tip.kueue.evicted" ns="status" components={{ b: <b /> }} />
        </span>
      ) : (
        t(r.key)
      ),
  }));
  return (
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 16 }}
      message={t('tip.title')}
      action={
        <a
          onClick={() => setOpen((v) => !v)}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            fontSize: 12,
          }}
        >
          <span>{open ? t('common:actions.collapse') : t('common:actions.expand')}</span>
          {open ? (
            <UpOutlined style={{ fontSize: 11 }} />
          ) : (
            <DownOutlined style={{ fontSize: 11 }} />
          )}
        </a>
      }
      description={
        open ? (
          <div style={{ lineHeight: 1.7 }}>
            <div style={{ marginTop: 4, marginBottom: 6 }}>
              <b>{t('tip.taskStatus')}</b>
              <span style={{ color: '#999', marginLeft: 8, fontSize: 12 }}>
                {t('tip.phaseSource', { source: phaseSource })}
              </span>
            </div>
            <StatusTable rows={phaseRows} badgeColor={phaseColor} />
            <div
              style={{
                marginTop: 8,
                padding: '6px 10px',
                background: 'rgba(0,0,0,0.02)',
                borderRadius: 4,
                fontSize: 12,
                color: 'rgba(0,0,0,0.55)',
              }}
            >
              <Trans i18nKey="tip.mechanism" ns="status" components={{ b: <b />, code: <code /> }} />
            </div>

            <div style={{ marginTop: 16, marginBottom: 6 }}>
              <b>{t('tip.kueueTitle')}</b>
              <span style={{ color: '#999', marginLeft: 8, fontSize: 12 }}>
                {t('tip.kueueSource')}
              </span>
            </div>
            <StatusTable rows={kueueRows} badgeColor={kueueStatusColor} />

            <div
              style={{
                marginTop: 12,
                padding: '8px 12px',
                background: 'rgba(0,0,0,0.02)',
                borderRadius: 6,
                fontSize: 12,
                color: 'rgba(0,0,0,0.55)',
              }}
            >
              <Trans i18nKey="tip.note" ns="status" components={{ b: <b /> }} />
            </div>
          </div>
        ) : null
      }
    />
  );
}
