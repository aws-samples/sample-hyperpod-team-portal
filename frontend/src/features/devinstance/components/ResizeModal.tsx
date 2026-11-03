import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Divider,
  Modal,
  Select,
  Space,
  Tooltip,
  Typography,
  theme,
} from 'antd';
import { InfoCircleOutlined, ReloadOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import {
  listResourceTemplates,
  resourceText,
  type ResourceTemplateItem,
} from '@/api/resource-templates';
import {
  POOL_OPTIONS,
  poolOfTemplate,
  templateInPool,
  type Pool,
} from '@/api/resource-pool';
import { ApiError } from '@/shared/api';
import SharedStoragePicker, {
  type StorageItem,
} from '@/shared/ui/SharedStoragePicker';
import { listWorkspaceS3, type WorkspaceS3Mount } from '@/features/workspace/api';
import { listSharedPVCs, resizeDevInstance } from '../api/client';
import type { DevInstanceDetail, SharedPVCInfo } from '../api/types';

const { Text } = Typography;

// ws 已挂载项 (合并 fsx+s3, 给 SharedStoragePicker adapt 用)。与创建表单同结构。
interface UnifiedWsMount {
  kind: 'fsx' | 's3';
  mount_path: string;
  pvc_name: string;
  access?: 'ro' | 'rw';
  isPrimary?: boolean;
}

interface Props {
  wsId: string;
  instance: DevInstanceDetail;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

/**
 * 改规格弹窗: 选资源池 + 资源模板 + 编辑挂载 → 下发 PATCH /resize。
 *
 * 规格由管理员维护的资源模板统一锁定 (与创建页 ResourceSection 同源, 用户不手填);
 * 资源池只读 (换池会与镜像家族错配, 需重建); 存储不可改 (EBS 无法扩容, /home/sagemaker-user 靠复用 PVC 保留)。
 * FSx/S3 挂载可增删, 全量下发 (预填当前挂载, 所见即所得)。运行中改会重建 Pod, 弹窗内明确提示。
 */
export default function ResizeModal({
  wsId,
  instance,
  open,
  onClose,
  onSuccess,
}: Props) {
  const { t } = useTranslation(['devinstance', 'common']);
  const { message, modal } = App.useApp();
  const { token } = theme.useToken();
  const [templates, setTemplates] = useState<ResourceTemplateItem[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [pool, setPool] = useState<Pool>(
    (instance.pool as Pool) || (instance.gpu_count > 0 ? 'gpu' : 'cpu'),
  );
  const [templateId, setTemplateId] = useState<string | undefined>();

  // 挂载: ws 可挂列表 + FSx/S3 选中态 (mount_path 当键, ws 内唯一)。
  const [mounts, setMounts] = useState<UnifiedWsMount[]>([]);
  const [loadingMounts, setLoadingMounts] = useState(false);
  const [fsxSelectedPaths, setFsxSelectedPaths] = useState<string[]>([]);
  const [s3SelectedPaths, setS3SelectedPaths] = useState<string[]>([]);

  const running = (instance.phase || '').includes('Available');

  const refresh = useCallback(() => {
    if (!wsId) return;
    setRefreshing(true);
    listResourceTemplates(wsId)
      .then(setTemplates)
      .catch(() => setTemplates([]))
      .finally(() => setRefreshing(false));
  }, [wsId]);

  // ws 可挂列表: 本人 permitted 的 FSx + ws 级 S3。
  //
  // 只列有权限的: 开发机当前挂载里若有本人现已无权限的 FSx (listSharedPVCs 只返
  // permitted, 查不到), 一律不显示、不预选 (预填按 kind 分桶, 查不到 kind 即丢弃) —
  // 全量下发时这类挂载随之移除 (保留也会被后端鉴权拦下)。
  const buildMounts = useCallback(
    (fsx: SharedPVCInfo[], s3: WorkspaceS3Mount[]): UnifiedWsMount[] => [
      ...fsx.map((m) => ({
        kind: 'fsx' as const,
        mount_path: m.mount_path ?? m.name,
        pvc_name: m.name,
        access: (m.access as 'ro' | 'rw' | null) ?? undefined,
        isPrimary: m.is_primary ?? false,
      })),
      ...s3.map((m) => ({
        kind: 's3' as const,
        mount_path: m.mount_path,
        pvc_name: m.pvc_name,
      })),
    ],
    [],
  );

  // ws 可挂载列表 (FSx shared-pvcs + S3); 共享存储刷新按钮也调 (不清空已选)。
  const reloadMounts = useCallback(() => {
    if (!wsId) return;
    setLoadingMounts(true);
    Promise.all([listSharedPVCs(wsId), listWorkspaceS3(wsId)])
      .then(([fsx, s3]) => setMounts(buildMounts(fsx, s3)))
      .catch((err) => {
        message.error(err instanceof ApiError ? err.message : t('resize.loadMountsFailed'));
        setMounts([]);
      })
      .finally(() => setLoadingMounts(false));
  }, [wsId, message, buildMounts, t]);

  // 打开时拉模板 + 挂载列表, 并按当前规格/挂载预选 (未命中留空由用户选)。
  useEffect(() => {
    if (!open) return;
    setPool((instance.pool as Pool) || (instance.gpu_count > 0 ? 'gpu' : 'cpu'));
    setRefreshing(true);
    listResourceTemplates(wsId)
      .then((list) => {
        setTemplates(list);
        const curCpu = instance.cpu_request_millicores / 1000;
        const curMem = instance.memory_request_mib / 1024;
        const hit = list.find(
          (tpl) =>
            (tpl.resource.gpu ?? 0) === instance.gpu_count &&
            tpl.resource.cpu_cores === curCpu &&
            Math.max(tpl.resource.mem_gib ?? 0, 8) === Math.max(curMem, 8),
        );
        setTemplateId(hit?.template_id);
      })
      .catch(() => setTemplates([]))
      .finally(() => setRefreshing(false));

    // 挂载列表拉回后, 按开发机当前 volume_mounts 预选。分桶用列表里每项的 kind:
    // 无权限 FSx 不在列表 (kind undefined) → 两桶都不选, 直接不显示。
    setLoadingMounts(true);
    Promise.all([listSharedPVCs(wsId), listWorkspaceS3(wsId)])
      .then(([fsx, s3]) => {
        const merged = buildMounts(fsx, s3);
        setMounts(merged);
        const kindOf = new Map(merged.map((m) => [m.mount_path, m.kind]));
        const cur = instance.volume_mounts ?? [];
        setFsxSelectedPaths(
          cur
            .map((v) => v.mount_path)
            .filter((p) => kindOf.get(p) === 'fsx'),
        );
        setS3SelectedPaths(
          cur
            .map((v) => v.mount_path)
            .filter((p) => kindOf.get(p) === 's3'),
        );
      })
      .catch(() => setMounts([]))
      .finally(() => setLoadingMounts(false));
    // 只在弹窗打开或切到别的开发机时初始化: 依赖 instance.id (稳定) 而非整个
    // instance 对象 —— 父组件轮询刷新会传入新 instance 引用, 若依赖对象会重跑本
    // effect 把 templateId/挂载选择重置回当前规格, 覆盖用户刚做的修改。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, wsId, instance.id]);

  const inPool = useMemo(
    () => templates.filter((tpl) => templateInPool(tpl, pool)),
    [templates, pool],
  );
  const selectedTpl = templates.find((tpl) => tpl.template_id === templateId);

  const fsxOptions: StorageItem[] = useMemo(
    () =>
      mounts
        .filter((m) => m.kind === 'fsx')
        .map((m) => ({
          id: m.mount_path,
          path: m.mount_path,
          access: m.access,
          isPrimary: m.isPrimary,
        })),
    [mounts],
  );
  const s3Options: StorageItem[] = useMemo(
    () =>
      mounts
        .filter((m) => m.kind === 's3')
        .map((m) => ({ id: m.mount_path, path: m.mount_path })),
    [mounts],
  );

  const handleSubmit = () => {
    if (!selectedTpl) {
      message.warning(t('create.resource.templateRequired'));
      return;
    }
    modal.confirm({
      centered: true,
      title: t('resize.confirmTitle'),
      content: t('resize.confirmContent'),
      okText: t('resize.confirmOk'),
      cancelText: t('common:actions.cancel'),
      onOk: () => doResize(),
    });
  };

  const doResize = async () => {
    if (!selectedTpl) return;
    const r = selectedTpl.resource;
    // 全量下发挂载 (含空表): 后端全量替换语义, 所见即所得。
    const allSelectedPaths = [...fsxSelectedPaths, ...s3SelectedPaths];
    // 只下发能解析到 pvc_name 的挂载; 理论上都能命中 (buildMounts 已含当前挂载),
    // 但兜底跳过异常项而非 throw, 避免二次确认 onOk 抛异常导致点击"没反应"。
    const volume_mounts = allSelectedPaths.flatMap((mp) => {
      const m = mounts.find((x) => x.mount_path === mp);
      return m ? [{ mount_path: mp, pvc_name: m.pvc_name }] : [];
    });
    setSubmitting(true);
    try {
      await resizeDevInstance(instance.id, {
        cpu_request_millicores: Math.round(r.cpu_cores * 1000),
        memory_request_mib: Math.round(Math.max(r.mem_gib ?? 0, 8) * 1024),
        gpu_count: r.gpu ?? 0,
        efa_count: r.efa ?? 0,
        volume_mounts,
      });
      message.success(t('resize.submitted'));
      onSuccess();
      onClose();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : t('resize.failed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title={t('resize.title')}
      open={open}
      width={760}
      onCancel={onClose}
      confirmLoading={submitting}
      okText={t('resize.okText')}
      cancelText={t('common:actions.cancel')}
      onOk={handleSubmit}
      okButtonProps={{ disabled: !selectedTpl }}
      destroyOnClose
    >
      <Space direction="vertical" size={16} style={{ width: '100%', marginTop: 8 }}>
        {running && (
          <Alert
            type="warning"
            showIcon
            message={t('resize.runningWarning')}
          />
        )}

        {/* 资源池 */}
        <div>
          <div style={{ marginBottom: 6 }}>
            <Text>{t('fields.resourcePool')}</Text>
            <Tooltip title={t('resize.poolTooltip')}>
              <InfoCircleOutlined style={{ color: '#999', marginLeft: 6 }} />
            </Tooltip>
          </div>
          <Select
            value={pool}
            options={POOL_OPTIONS}
            style={{ width: '100%' }}
            disabled
          />
        </div>

        {/* 资源模板 */}
        <div>
          <div style={{ marginBottom: 6 }}>
            <Text>{t('fields.resourceTemplate')}</Text>
            <Tooltip title={t('create.resource.templateTooltip')}>
              <InfoCircleOutlined style={{ color: '#999', marginLeft: 6 }} />
            </Tooltip>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Select
              placeholder={t('create.resource.templatePlaceholder')}
              style={{ flex: 1 }}
              value={templateId}
              onChange={setTemplateId}
              options={inPool.map((tpl) => ({
                label: `${poolOfTemplate(tpl) === 'gpu' ? 'GPU' : 'CPU'} · ${resourceText(tpl.resource)} · ${tpl.name}`,
                value: tpl.template_id,
              }))}
            />
            <Tooltip title={t('common:actions.refresh')}>
              <Button
                type="text"
                icon={<ReloadOutlined style={{ color: '#999' }} />}
                loading={refreshing}
                onClick={refresh}
              />
            </Tooltip>
          </div>
          {templates.length === 0 && !refreshing && (
            <div style={{ fontSize: 12, marginTop: 6, color: token.colorError }}>
              <InfoCircleOutlined style={{ marginRight: 6 }} />
              {t('resize.noTemplates')}
            </div>
          )}
        </div>

        {/* 目标规格灰带 (只读) */}
        <div>
          <div style={{ marginBottom: 6 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>{t('resize.targetSpec')}</Text>
          </div>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 24,
              height: 32,
              whiteSpace: 'nowrap',
              padding: '0 12px',
              borderRadius: token.borderRadius,
              background: token.colorFillTertiary,
              border: `1px solid ${token.colorBorderSecondary}`,
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {(
              [
                ['GPU', selectedTpl ? selectedTpl.resource.gpu : '—', 'unitCard'],
                ['CPU', selectedTpl ? selectedTpl.resource.cpu_cores : '—', 'unitCore'],
                [t('spec.memory'), selectedTpl ? Math.max(selectedTpl.resource.mem_gib ?? 0, 8) : '—', 'GiB'],
                ['EFA', selectedTpl ? (selectedTpl.resource.efa ?? 0) : '—', 'unitAdapter'],
              ] as const
            ).map(([label, val, unit], i) => (
              <span key={label as string} style={{ display: 'flex', alignItems: 'center' }}>
                {i > 0 && (
                  <span style={{ width: 1, height: 14, background: token.colorBorderSecondary, marginRight: 24 }} />
                )}
                <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>{label}</Text>
                <Text strong>{val}</Text>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>
                  {unit === 'GiB'
                    ? unit
                    : t(`spec.${unit}`, { count: Number(val) || 0 })}
                </Text>
              </span>
            ))}
          </div>
        </div>

        <Divider style={{ margin: '4px 0' }} />

        {/* 共享存储 (可增删, 全量下发) */}
        <div>
          <div style={{ marginBottom: 6 }}>
            <Text>{t('fields.sharedStorage')}</Text>
            <Tooltip title={t('resize.storageTooltip')}>
              <InfoCircleOutlined style={{ color: '#999', marginLeft: 6 }} />
            </Tooltip>
          </div>
          <SharedStoragePicker
            fsxOptions={fsxOptions}
            s3Options={s3Options}
            fsxSelected={fsxSelectedPaths}
            s3Selected={s3SelectedPaths}
            onFsxChange={setFsxSelectedPaths}
            onS3Change={setS3SelectedPaths}
            loading={loadingMounts}
            onReload={reloadMounts}
          />
        </div>

        <Alert
          type="info"
          showIcon
          message={t('resize.storageNote')}
        />
      </Space>
    </Modal>
  );
}
