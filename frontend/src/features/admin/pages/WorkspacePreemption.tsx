import { useEffect, useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { PageContainer, ProCard } from '@ant-design/pro-components';
import { Alert, Popconfirm, Switch, Table, Tag, message } from 'antd';
import { DownOutlined, UpOutlined } from '@ant-design/icons';
import { ApiError } from '@/shared/api';
import { useAppStore } from '@/store';
import { listWorkspaces, type Workspace } from '@/features/workspace/api';
import { getPreemption, setPreemption } from '@/api/priority';
import PageDescription from '@/shared/ui/PageDescription';

/**
 * 工作空间抢占开关 (per-workspace · ClusterQueue withinClusterQueue).
 *
 * 原本是「优先级管理」页里的 tab2, 拆出来独立成菜单项,
 * 因为它和「优先级档位 (WorkloadPriorityClass)」管理粒度不同 —
 * 档位是平台级 N 个档, 抢占开关是 per-workspace 一行一关, 二者放一起易混。
 */

interface PreemptionRow {
  ws: Workspace;
  within?: 'Never' | 'LowerPriority';
  loading: boolean;
}

export default function WorkspacePreemption() {
  const { t } = useTranslation(['admin', 'common']);
  const isAdmin = useAppStore((s) => s.currentUser?.is_admin ?? false);
  const [rows, setRows] = useState<PreemptionRow[]>([]);
  const [tipOpen, setTipOpen] = useState(false);

  useEffect(() => {
    listWorkspaces()
      .then((wss) => {
        setRows(wss.map((ws) => ({ ws, loading: true })));
        wss.forEach((ws) => {
          getPreemption(ws.id)
            .then((p) =>
              setRows((prev) =>
                prev.map((r) =>
                  r.ws.id === ws.id
                    ? { ...r, within: p.within_cluster_queue, loading: false }
                    : r,
                ),
              ),
            )
            .catch(() =>
              setRows((prev) =>
                prev.map((r) => (r.ws.id === ws.id ? { ...r, loading: false } : r)),
              ),
            );
        });
      })
      .catch((err) => message.error(t('preemption.loadWsFailed', { error: String(err) })));
  }, [t]);

  const toggle = async (ws: Workspace, on: boolean) => {
    const target = on ? 'LowerPriority' : 'Never';
    try {
      const p = await setPreemption(ws.id, target);
      setRows((prev) =>
        prev.map((r) => (r.ws.id === ws.id ? { ...r, within: p.within_cluster_queue } : r)),
      );
      message.success(
        t(on ? 'preemption.enabledMsg' : 'preemption.disabledMsg', {
          name: ws.display_name || ws.name,
        }),
      );
    } catch (err) {
      const msg = err instanceof ApiError ? `${err.status} ${err.message}` : String(err);
      message.error(t('preemption.switchFailed', { error: msg }));
    }
  };

  const columns = [
    {
      title: 'Workspace',
      key: 'ws',
      render: (_: unknown, r: PreemptionRow) => r.ws.display_name || r.ws.name,
    },
    {
      title: 'Namespace',
      key: 'ns',
      render: (_: unknown, r: PreemptionRow) => r.ws.namespace,
    },
    {
      title: t('preemption.columns.status'),
      key: 'within',
      render: (_: unknown, r: PreemptionRow) =>
        r.loading ? (
          t('preemption.loading')
        ) : r.within === 'LowerPriority' ? (
          <Tag color="green">{t('preemption.statusOn')}</Tag>
        ) : (
          <Tag>{t('preemption.statusOff')}</Tag>
        ),
    },
    {
      title: t('preemption.columns.toggle'),
      key: 'toggle',
      width: 120,
      render: (_: unknown, r: PreemptionRow) =>
        isAdmin ? (
          <Popconfirm
            title={
              r.within === 'LowerPriority'
                ? t('preemption.confirmOffTitle')
                : t('preemption.confirmOnTitle')
            }
            description={
              r.within === 'LowerPriority'
                ? t('preemption.confirmOffDesc')
                : t('preemption.confirmOnDesc')
            }
            onConfirm={() => toggle(r.ws, r.within !== 'LowerPriority')}
          >
            <Switch checked={r.within === 'LowerPriority'} disabled={r.loading} />
          </Popconfirm>
        ) : (
          <Tag>{t('shared.readOnly')}</Tag>
        ),
    },
  ];

  return (
    <PageContainer header={{ title: t('preemption.title') }}>
      <PageDescription>{t('preemption.description')}</PageDescription>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={t('preemption.rulesTitle')}
        action={
          <a
            onClick={() => setTipOpen((v) => !v)}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              fontSize: 12,
            }}
          >
            <span>{tipOpen ? t('common:actions.collapse') : t('common:actions.expand')}</span>
            {tipOpen ? <UpOutlined style={{ fontSize: 11 }} /> : <DownOutlined style={{ fontSize: 11 }} />}
          </a>
        }
        description={
          tipOpen ? (
            <div style={{ lineHeight: 1.8 }}>
              <div style={{ marginBottom: 8 }}>
                <Trans ns="admin" i18nKey="preemption.when" components={{ b: <b /> }} />
              </div>
              <ol style={{ margin: '0 0 12px', paddingLeft: 20 }}>
                <li>{t('preemption.cond1')}</li>
                <li>{t('preemption.cond2')}</li>
                <li>{t('preemption.cond3')}</li>
              </ol>
              <div style={{ marginBottom: 8 }}>
                <Trans ns="admin" i18nKey="preemption.boundaryTitle" components={{ b: <b /> }} />
              </div>
              <ul style={{ margin: '0 0 12px', paddingLeft: 20 }}>
                <li>{t('preemption.boundary1')}</li>
                <li>{t('preemption.boundary2')}</li>
                <li>{t('preemption.boundary3')}</li>
                <li>{t('preemption.boundary4')}</li>
              </ul>
              <div>
                <Trans ns="admin" i18nKey="preemption.advice" components={{ b: <b /> }} />
              </div>
            </div>
          ) : null
        }
      />
      {!isAdmin && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('shared.readOnlyMode')}
          description={t('preemption.readOnlyDesc')}
        />
      )}
      <ProCard>
        <Table
          rowKey={(r) => r.ws.id}
          columns={columns}
          dataSource={rows}
          pagination={false}
          size="small"
        />
      </ProCard>
    </PageContainer>
  );
}
