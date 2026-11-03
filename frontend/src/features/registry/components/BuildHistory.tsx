import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge, Button, Modal, Space, Spin, Table, Tag, Tooltip, Typography, message } from 'antd';
import { CopyOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import {
  getImageBuildLogs,
  listImageBuilds,
  type ImageBuild,
  type ImageUse,
} from '@/api/registry';
import { imageUseLabel } from '../mock';

dayjs.extend(relativeTime); // 创建时间列用 fromNow()

const { Text } = Typography;

// 文案存 key, 渲染时再 t()。
const STATUS = {
  building: { s: 'processing', labelKey: 'buildHistory.status.building' },
  success: { s: 'success', labelKey: 'buildHistory.status.success' },
  failed: { s: 'error', labelKey: 'buildHistory.status.failed' },
} as const;

// 用途 Tag 颜色, 与可用镜像列表一致
const USE_TAG_COLOR: Record<ImageUse, string> = {
  dev: 'geekblue',
  training: 'green',
  inference: 'purple',
};

/**
 * 构建历史: 列本 ws 的构建记录 + 状态 + Dockerfile/日志查看。
 * 有"构建中"记录时轮询 (每次 list 触发后端读取时状态回收)。
 */
export default function BuildHistory({
  wsId,
  refreshKey,
  onBuildingCount,
}: {
  wsId: string;
  refreshKey: number;
  /** 回传"构建中"数量给父组件 (显示 Tab 角标)。 */
  onBuildingCount?: (n: number) => void;
}) {
  const { t } = useTranslation(['registry', 'common']);
  const [rows, setRows] = useState<ImageBuild[]>([]);
  const [loading, setLoading] = useState(false);
  // Dockerfile 弹窗 (直接用 row.dockerfile, 无需请求)
  const [dfRow, setDfRow] = useState<ImageBuild | null>(null);
  // 日志弹窗 (打开时拉 CloudWatch 文本 + 完整 log group / region / 控制台链接)
  const [logRow, setLogRow] = useState<ImageBuild | null>(null);
  const [logText, setLogText] = useState('');
  const [logGroup, setLogGroup] = useState('');
  const [logUrl, setLogUrl] = useState('');
  const [logLoading, setLogLoading] = useState(false);
  // 翻页: 后端返回的 next_token (空=已到末尾); "加载更多"续拉 append。
  const [logToken, setLogToken] = useState('');
  const [logMoreLoading, setLogMoreLoading] = useState(false);

  const load = useCallback(() => {
    if (!wsId) return;
    setLoading(true);
    listImageBuilds(wsId)
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [wsId]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  // 有构建中的记录 → 每 15s 轮询 (触发后端回收状态) + 回传数量给父组件
  useEffect(() => {
    const n = rows.filter((r) => r.status === 'building').length;
    onBuildingCount?.(n);
    if (n === 0) return;
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, [rows, load, onBuildingCount]);

  const openLogs = useCallback(
    (r: ImageBuild) => {
      setLogRow(r);
      setLogText('');
      setLogGroup('');
      setLogUrl('');
      setLogToken('');
      setLogLoading(true);
      getImageBuildLogs(wsId, r.id)
        .then((res) => {
          setLogText(res.log_text || t('buildHistory.noLogs'));
          setLogGroup(res.log_group || '');
          setLogToken(res.next_token || '');
          // 优先后端 deepLink; 没有则用 log_group + stream(codebuild_id 的 uuid 段) 自拼
          const stream = r.codebuild_id.includes(':')
            ? r.codebuild_id.split(':')[1]
            : '';
          const fallback =
            res.log_group && res.region
              ? `https://${res.region}.console.aws.amazon.com/cloudwatch/home?region=${res.region}#logsV2:log-groups/log-group/${encodeURIComponent(res.log_group)}${stream ? `/log-events/${encodeURIComponent(stream)}` : ''}`
              : '';
          setLogUrl(res.logs_url || fallback);
        })
        .catch(() => setLogText(t('buildHistory.logsFailed')))
        .finally(() => setLogLoading(false));
    },
    [wsId, t],
  );

  // 加载更多: 用 logToken 续拉下一页, append 到已有日志。
  const loadMoreLogs = useCallback(() => {
    if (!logRow || !logToken) return;
    setLogMoreLoading(true);
    getImageBuildLogs(wsId, logRow.id, logToken)
      .then((res) => {
        if (res.log_text) setLogText((prev) => prev + res.log_text);
        setLogToken(res.next_token || '');
      })
      .catch(() => message.error(t('buildHistory.loadMoreFailed')))
      .finally(() => setLogMoreLoading(false));
  }, [wsId, logRow, logToken, t]);

  const copyDockerfile = () => {
    if (!dfRow?.dockerfile) return;
    navigator.clipboard
      .writeText(dfRow.dockerfile)
      .then(() => message.success(t('buildHistory.dockerfileCopied')))
      .catch(() => message.error(t('common:messages.copyFailed')));
  };

  const columns = [
    {
      title: t('buildHistory.columns.image'),
      dataIndex: 'target_tag',
      render: (v: string) => (
        <Text style={{ fontFamily: 'monospace', fontSize: 13 }}>{v}</Text>
      ),
    },
    {
      title: t('buildHistory.columns.uses'),
      dataIndex: 'uses',
      width: 130,
      render: (uses: ImageUse[]) => (
        <Space size={4} wrap>
          {(uses || []).map((u) => (
            <Tag key={u} color={USE_TAG_COLOR[u]} style={{ marginInlineEnd: 0 }}>
              {imageUseLabel(u)}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: t('common:fields.status'),
      dataIndex: 'status',
      width: 110, // en: "Succeeded" 比 "成功" 长
      render: (s: string) => {
        const c = Object.hasOwn(STATUS, s) ? STATUS[s as keyof typeof STATUS] : undefined;
        return <Badge status={c?.s ?? 'default'} text={c ? t(c.labelKey) : s} />;
      },
    },
    {
      title: t('buildHistory.columns.spec'),
      dataIndex: 'compute_type',
      width: 90,
      render: (v: string) => v.replace('BUILD_GENERAL1_', '') || '—',
    },
    { title: t('buildHistory.columns.submitter'), dataIndex: 'creator_username', width: 120 },
    {
      title: t('common:fields.createdAt'),
      dataIndex: 'created_at',
      width: 120,
      render: (v: string) =>
        v ? (
          <Tooltip title={dayjs(v).format('YYYY-MM-DD HH:mm:ss')}>
            <span>{dayjs(v).fromNow()}</span>
          </Tooltip>
        ) : (
          '-'
        ),
    },
    {
      title: t('common:fields.actions'),
      key: 'action',
      width: 150,
      render: (_: unknown, r: ImageBuild) => (
        <Space size="middle">
          <a onClick={() => setDfRow(r)}>Dockerfile</a>
          <a onClick={() => openLogs(r)}>{t('buildHistory.columns.logs')}</a>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
      />

      {/* Dockerfile 弹窗 (带复制) */}
      <Modal
        title={dfRow ? `Dockerfile · ${dfRow.target_tag}` : 'Dockerfile'}
        open={dfRow !== null}
        onCancel={() => setDfRow(null)}
        footer={null}
        width={760}
      >
        <div style={{ textAlign: 'right', marginBottom: 8 }}>
          <Button size="small" icon={<CopyOutlined />} onClick={copyDockerfile}>
            {t('common:actions.copy')}
          </Button>
        </div>
        <pre
          style={{
            maxHeight: 480,
            overflow: 'auto',
            background: '#f6f8fa',
            color: '#1f1f1f',
            fontFamily: '"JetBrains Mono", "Fira Code", Menlo, monospace',
            fontSize: 12,
            lineHeight: 1.55,
            padding: '8px 12px',
            borderRadius: 6,
            border: '1px solid #e8e8e8',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
            margin: 0,
          }}
        >
          {dfRow?.dockerfile || t('buildHistory.dockerfileEmpty')}
        </pre>
      </Modal>

      {/* 日志弹窗 (视觉对齐训练任务日志: 等宽/浅底/边框) */}
      <Modal
        title={
          logRow
            ? t('buildHistory.logTitle', { tag: logRow.target_tag })
            : t('buildHistory.logTitleEmpty')
        }
        open={logRow !== null}
        onCancel={() => setLogRow(null)}
        footer={null}
        width={860}
      >
        <div
          style={{
            background: '#f6f8fa',
            color: '#1f1f1f',
            fontFamily: '"JetBrains Mono", "Fira Code", Menlo, monospace',
            fontSize: 12,
            lineHeight: 1.55,
            height: 520,
            overflow: 'auto',
            padding: '8px 12px',
            borderRadius: 6,
            border: '1px solid #e8e8e8',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
          }}
        >
          {logLoading ? (
            <div
              style={{
                height: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Spin tip={t('buildHistory.fetching')} />
            </div>
          ) : (
            logText
          )}
        </div>
        {!logLoading && logToken ? (
          <div style={{ textAlign: 'center', marginTop: 8 }}>
            <Button size="small" loading={logMoreLoading} onClick={loadMoreLogs}>
              {t('buildHistory.loadMore')}
            </Button>
          </div>
        ) : null}
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
          {t('buildHistory.dataSource')}
          {logGroup ? (
            <>
              {' · '}
              <Text code style={{ fontSize: 12 }}>
                {logGroup}
              </Text>
            </>
          ) : null}
          {logUrl ? (
            <>
              {' · '}
              <a href={logUrl} target="_blank" rel="noreferrer">
                {t('buildHistory.openConsole')}
              </a>
            </>
          ) : null}
        </Text>
      </Modal>
    </>
  );
}
