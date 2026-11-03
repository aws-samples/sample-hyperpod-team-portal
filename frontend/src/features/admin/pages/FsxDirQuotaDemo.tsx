import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Progress,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PageContainer, ProCard } from '@ant-design/pro-components';
import {
  listFsxDirectories,
  createFsxDirectory,
  updateFsxQuota,
  type DirQuota,
} from '@/features/admin/api/fsxQuota';
import { listFsxFilesystems, fsxLabel, type FsxOption } from '@/features/monitoring/api';
import { ApiError } from '@/shared/api';
import i18n from '@/shared/i18n';
import {
  CheckCircleFilled,
  ExclamationCircleFilled,
  CloseCircleFilled,
  PlusOutlined,
  ReloadOutlined,
  FolderOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons';

const { Text } = Typography;

// ============================================================
// FSx 一级目录配额 · 接真实后端 (/admin/fsx-quota)。
// 用量: lfs quota -p 读; 配额: lfs setquota -p 设 (project quota, 原生 2.15 fs)。
// 目录名/gid/project id 后端自动分配, 前端只填目录名 + 硬限。
// CloudWatch 监控图已移至「监控 / FSx」页 (所有用户可看)。
// ============================================================

// soft 线 = 硬限 80% (后端同口径); 建/改配额时只填硬限, soft 只读推算。
const SOFT_RATIO = 0.8;

// 展示真实错误信息 (带 HTTP 状态码), 不吞真因; 只在信息为空时兜底。
function friendlyError(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    const raw = (e.message || '').trim();
    if (e.status && raw) return `${raw} (HTTP ${e.status})`;
    if (raw) return raw;
    if (e.status) return i18n.t('fsxQuota.requestFailed', { ns: 'admin', status: e.status });
  }
  if (e instanceof Error && e.message) return e.message;
  return fallback;
}

/** 用量状态: 依占比给 status 色 + 图标 (dataviz: status 色永远配图标+文字, 不只靠色)。 */
function usageStatus(pct: number): {
  color: string; // AntD Progress strokeColor
  tagColor: string;
  icon: React.ReactNode;
  label: string;
} {
  // 低饱和柔和色 (进度条/百分比文字用), 避免页面花哨; Tag 仍用 antd 预设语义色
  if (pct >= 100) {
    return { color: '#c96a6a', tagColor: 'error', icon: <CloseCircleFilled />, label: i18n.t('fsxQuota.status.over', { ns: 'admin' }) };
  }
  // soft 线 80% 起提示 "接近上限" (与后端 soft = 硬限 80% 对齐)
  if (pct >= 80) {
    return { color: '#d4a850', tagColor: 'warning', icon: <ExclamationCircleFilled />, label: i18n.t('fsxQuota.status.near', { ns: 'admin' }) };
  }
  return { color: '#6aa877', tagColor: 'success', icon: <CheckCircleFilled />, label: i18n.t('fsxQuota.status.normal', { ns: 'admin' }) };
}

export default function FsxDirQuotaDemo() {
  const { t } = useTranslation(['admin', 'common']);
  const [rows, setRows] = useState<DirQuota[]>([]);
  const [totalGib, setTotalGib] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 多 FSx: 顶部下拉选盘, 给哪个盘调配额。
  const [fsList, setFsList] = useState<FsxOption[]>([]);
  const [fsId, setFsId] = useState<string>('');
  const [fsLoading, setFsLoading] = useState(true); // FSx 列表加载中 (describe 各盘, 秒级)

  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();
  const [creating, setCreating] = useState(false);

  const [editTarget, setEditTarget] = useState<DirQuota | null>(null);
  const [editForm] = Form.useForm();
  const [editing, setEditing] = useState(false);

  // 建目录表单里实时推算 soft (= 硬限 80%), 只读展示
  const createHardGib = Form.useWatch<number | undefined>('hardGib', createForm);
  const editHardGib = Form.useWatch<number | undefined>('hardGib', editForm);

  const loadDirectories = useCallback(async (fs: string) => {
    if (!fs) return;
    setLoading(true);
    setError(null);
    try {
      const data = await listFsxDirectories(fs);
      setRows(data.directories);
      setTotalGib(data.totalGib);
    } catch (e) {
      setError(friendlyError(e, t('fsxQuota.loadDirsFailed')));
    } finally {
      setLoading(false);
    }
  }, [t]);

  // 进页面先拉 FSx 列表, 默认选第一个。
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setFsLoading(true);
      try {
        const list = await listFsxFilesystems();
        if (cancelled) return;
        setFsList(list);
        if (list.length > 0) setFsId(list[0].filesystemId);
      } catch (e) {
        if (!cancelled) setError(friendlyError(e, t('fsxQuota.loadListFailed')));
      } finally {
        if (!cancelled) setFsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  useEffect(() => {
    if (fsId) void loadDirectories(fsId);
  }, [fsId, loadDirectories]);

  // 顶部总览统计: 用量汇总 + 已分配配额之和 (allocated = 各目录 hard 求和)。
  const summary = useMemo(() => {
    const used = rows.reduce((s, r) => s + r.usedGib, 0);
    const allocated = rows.reduce((s, r) => s + r.hardGib, 0);
    const over = rows.filter((r) => r.pct >= 100).length;
    return {
      used: Math.round(used),
      allocated: Math.round(allocated),
      dirCount: rows.length,
      over,
    };
  }, [rows]);

  // 复用 team 下拉项: 按 gid 去重, label 展示该 gid 归属的目录名 (多个用 、 连)。
  const gidOptions = useMemo(() => {
    const byGid = new Map<number, string[]>();
    for (const r of rows) {
      const names = byGid.get(r.gid) ?? [];
      names.push(r.name);
      byGid.set(r.gid, names);
    }
    return [...byGid.entries()].map(([gid, names]) => ({
      value: gid,
      label: t('fsxQuota.gidOption', { gid, names: names.join(t('fsxQuota.nameSeparator')) }),
    }));
  }, [rows, t]);

  const handleCreate = () => {
    createForm.validateFields().then(async (v) => {
      // 提交前校验: 所有现存目录 hard 之和 + 新目录 hard 不得超 FS 总容量。
      // 新目录尚不存在, 全部现存目录都计入 other。超过则拦下不建 (后端亦有兜底)。
      const otherSum = rows.reduce((s, r) => s + r.hardGib, 0);
      const projected = otherSum + v.hardGib;
      if (totalGib != null && projected > totalGib) {
        message.error(
          t('fsxQuota.exceedsCapacity', { projected, total: totalGib, other: otherSum }),
        );
        return;
      }
      setCreating(true);
      try {
        const created = await createFsxDirectory(fsId, v.name, v.hardGib, v.gid);
        setRows((prev) => [...prev, created]);
        message.success(
          t('fsxQuota.createdMsg', {
            name: created.name,
            hard: created.hardGib,
            gid: created.gid,
          }),
        );
        createForm.resetFields();
        setCreateOpen(false);
        // 后端可能有汇总副作用, 刷新对齐
        void loadDirectories(fsId);
      } catch (e) {
        message.error(e instanceof ApiError ? e.message : t('fsxQuota.createFailed'));
      } finally {
        setCreating(false);
      }
    });
  };

  const handleEdit = () => {
    if (!editTarget) return;
    editForm.validateFields().then(async (v) => {
      // 提交前校验: 排除被改目录 (旧配额将被新值替换), 其余 hard 之和 + 新值不得超总容量。
      const otherSum = rows.reduce(
        (s, r) => (r.name === editTarget.name ? s : s + r.hardGib),
        0,
      );
      const projected = otherSum + v.hardGib;
      if (totalGib != null && projected > totalGib) {
        message.error(
          t('fsxQuota.exceedsCapacity', { projected, total: totalGib, other: otherSum }),
        );
        return;
      }
      setEditing(true);
      try {
        const updated = await updateFsxQuota(fsId, editTarget.name, v.hardGib);
        setRows((prev) => prev.map((r) => (r.name === updated.name ? updated : r)));
        message.success(
          t('fsxQuota.updatedMsg', { name: updated.name, hard: updated.hardGib }),
        );
        setEditTarget(null);
      } catch (e) {
        message.error(e instanceof ApiError ? e.message : t('fsxQuota.updateFailed'));
      } finally {
        setEditing(false);
      }
    });
  };

  const openEdit = (r: DirQuota) => {
    // Form 常驻挂载 (forceRender), 实例始终在 → 直接同步赋值该目录当前硬限, 立即生效。
    editForm.setFieldsValue({ hardGib: r.hardGib });
    setEditTarget(r);
  };

  const columns: ColumnsType<DirQuota> = [
    {
      title: t('fsxQuota.columns.directory'),
      dataIndex: 'name',
      width: 200,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Space size={6}>
            <FolderOutlined style={{ color: '#898781' }} />
            <Text strong style={{ fontFamily: 'monospace' }}>/{r.name}</Text>
          </Space>
        </Space>
      ),
    },
    {
      title: 'GID',
      dataIndex: 'gid',
      width: 80,
      render: (v) => <Text style={{ fontVariantNumeric: 'tabular-nums' }}>{v}</Text>,
    },
    {
      title: 'PID',
      dataIndex: 'pid',
      width: 80,
      render: (v) => <Text style={{ fontVariantNumeric: 'tabular-nums' }}>{v}</Text>,
    },
    {
      title: t('fsxQuota.columns.usage'),
      width: 340,
      render: (_, r) => {
        const pct = Math.round(r.pct);
        const st = usageStatus(pct);
        return (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
              <Text style={{ fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
                {r.usedGib} / {r.softGib} / {r.hardGib} GiB
              </Text>
              <Text style={{ fontSize: 12, color: st.color, fontVariantNumeric: 'tabular-nums' }}>
                {pct}%
              </Text>
            </div>
            <Progress
              percent={Math.min(pct, 100)}
              strokeColor={st.color}
              showInfo={false}
              size="small"
            />
          </div>
        );
      },
    },
    {
      title: t('common:fields.status'),
      width: 120,
      render: (_, r) => {
        const st = usageStatus(Math.round(r.pct));
        return (
          <Tag icon={st.icon} color={st.tagColor}>
            {st.label}
          </Tag>
        );
      },
    },
    {
      title: t('common:fields.actions'),
      width: 100,
      render: (_, r) => <a onClick={() => openEdit(r)}>{t('fsxQuota.editQuota')}</a>,
    },
  ];

  return (
    <PageContainer
      header={{
        title: (
          <Space size={6}>
            {t('fsxQuota.title')}
            <Tooltip title={t('fsxQuota.titleTip')}>
              <QuestionCircleOutlined style={{ color: '#999', fontSize: 14, cursor: 'help' }} />
            </Tooltip>
          </Space>
        ),
      }}
      extra={[
        <Select
          key="fs"
          style={{ minWidth: 200 }}
          value={fsId || undefined}
          loading={fsLoading}
          disabled={fsLoading}
          placeholder={fsLoading ? t('fsxQuota.loadingFsx') : t('fsxQuota.selectFsx')}
          onChange={(v) => setFsId(v)}
          options={fsList.map((f) => ({
            value: f.filesystemId,
            label: fsxLabel(f),
          }))}
        />,
        <Button
          key="refresh"
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={() => void loadDirectories(fsId)}
        >
          {t('common:actions.refresh')}
        </Button>,
        <Button key="create" type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)} disabled={!fsId}>
          {t('fsxQuota.createDirectory')}
        </Button>,
      ]}
    >
      {/* 顶部总览: FSx 总容量 (FS 真实 StorageCapacity) + 已用 / 已分配 / 目录数 / 超额 */}
      <ProCard gutter={16} style={{ marginBottom: 16 }} ghost>
        <ProCard bordered>
          <Statistic
            title={t('fsxQuota.stats.total')}
            value={totalGib ?? '—'}
            suffix={totalGib != null ? 'GiB' : undefined}
          />
        </ProCard>
        <ProCard bordered>
          <Statistic
            title={
              <Space size={4}>
                {t('fsxQuota.stats.used')}
                <Tooltip title={t('fsxQuota.stats.usedTip')}>
                  <QuestionCircleOutlined style={{ color: '#999', fontSize: 13, cursor: 'help' }} />
                </Tooltip>
              </Space>
            }
            value={summary.used}
            suffix="GiB"
          />
        </ProCard>
        <ProCard bordered>
          <Statistic
            title={
              <Space size={4}>
                {t('fsxQuota.stats.allocated')}
                <Tooltip title={t('fsxQuota.stats.allocatedTip')}>
                  <QuestionCircleOutlined style={{ color: '#999', fontSize: 13, cursor: 'help' }} />
                </Tooltip>
              </Space>
            }
            value={summary.allocated}
            suffix="GiB"
            valueStyle={
              totalGib != null && summary.allocated > totalGib
                ? { color: '#d4a850' }
                : undefined
            }
          />
        </ProCard>
        <ProCard bordered>
          <Statistic title={t('fsxQuota.stats.dirCount')} value={summary.dirCount} />
        </ProCard>
        <ProCard bordered>
          <Statistic
            title={t('fsxQuota.stats.overCount')}
            value={summary.over}
            valueStyle={{ color: summary.over > 0 ? '#c96a6a' : '#6aa877' }}
          />
        </ProCard>
      </ProCard>

      {/* 目录配额表 (加载失败时错误收进表格空状态, 不用整块大红 banner) */}
      <ProCard bordered style={{ marginBottom: 16 }}>
        <Table<DirQuota>
          rowKey="name"
          columns={columns}
          dataSource={error ? [] : rows}
          loading={loading || fsLoading}
          pagination={false}
          size="middle"
          locale={{
            emptyText: error ? (
              <div style={{ padding: '24px 0', color: 'rgba(0,0,0,0.45)' }}>
                <div style={{ marginBottom: 8 }}>{error}</div>
                <Button size="small" icon={<ReloadOutlined />} onClick={() => void loadDirectories(fsId)}>
                  {t('common:actions.retry')}
                </Button>
              </div>
            ) : undefined,
          }}
        />
      </ProCard>

      {/* 创建目录弹窗: 只填 目录名 + 硬限 (gid/权限/project id 后端自动; soft = 硬限 80% 推算) */}
      <Modal
        title={t('fsxQuota.createDirectory')}
        open={createOpen}
        onOk={handleCreate}
        confirmLoading={creating}
        onCancel={() => setCreateOpen(false)}
        okText={t('common:actions.create')}
        cancelText={t('common:actions.cancel')}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ margin: '8px 0 16px' }}
          message={t('fsxQuota.createForm.alert')}
        />
        <Form form={createForm} layout="vertical">
          <Form.Item
            name="name"
            label={t('fsxQuota.createForm.nameLabel')}
            rules={[
              { required: true, message: t('fsxQuota.createForm.nameRequired') },
              { pattern: /^[a-z0-9][a-z0-9-]*$/, message: t('fsxQuota.createForm.namePattern') },
            ]}
            extra={t('fsxQuota.createForm.nameExtra')}
          >
            <Input placeholder="team-name" addonBefore="/" />
          </Form.Item>
          <Form.Item
            name="gid"
            label={t('fsxQuota.createForm.gidLabel')}
            extra={t('fsxQuota.createForm.gidExtra')}
          >
            <Select
              allowClear
              placeholder={t('fsxQuota.createForm.gidPlaceholder')}
              options={gidOptions}
            />
          </Form.Item>
          <Form.Item
            name="hardGib"
            label={t('fsxQuota.hardLabel')}
            rules={[{ required: true, message: t('fsxQuota.hardRequired') }]}
            initialValue={100}
            extra={
              createHardGib
                ? t('fsxQuota.softHintValue', { soft: Math.floor(createHardGib * SOFT_RATIO) })
                : t('fsxQuota.softHintEmpty')
            }
          >
            <InputNumber min={1} style={{ width: '100%' }} addonAfter="GiB" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 改配额弹窗: 只改硬限, soft 随硬限 80% 联动 (后端推算) */}
      {/* forceRender + 不 destroyOnClose: Form 常驻挂载, 实例始终连着 —— openEdit 里
          同步 setFieldsValue 立即生效 (不闪、不错)。注: editForm 是 useForm 单例, 其
          store 持久, initialValues 只在首挂载生效, 故必须 setFieldsValue 主动赋值。 */}
      <Modal
        title={
          editTarget ? t('fsxQuota.editModalTitle', { name: editTarget.name }) : t('fsxQuota.editQuota')
        }
        open={editTarget != null}
        onOk={handleEdit}
        confirmLoading={editing}
        onCancel={() => setEditTarget(null)}
        okText={t('common:actions.save')}
        cancelText={t('common:actions.cancel')}
        forceRender
      >
        <Form form={editForm} layout="vertical">
          <Form.Item
            name="hardGib"
            label={t('fsxQuota.hardLabel')}
            rules={[{ required: true, message: t('fsxQuota.hardRequired') }]}
            extra={
              editHardGib
                ? t('fsxQuota.softHintValue', { soft: Math.floor(editHardGib * SOFT_RATIO) })
                : t('fsxQuota.softHintEmpty')
            }
          >
            <InputNumber min={1} style={{ width: '100%' }} addonAfter="GiB" />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}
