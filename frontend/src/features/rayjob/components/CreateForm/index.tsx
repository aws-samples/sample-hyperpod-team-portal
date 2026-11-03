import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Anchor,
  Button,
  Col,
  Divider,
  Drawer,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Spin,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  MinusCircleOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
  RocketOutlined,
} from '@ant-design/icons';
import { ProCard } from '@ant-design/pro-components';
import { ApiError } from '@/shared/api';
import { createRayJob, getRayJob, previewRayJob } from '../../api/client';
import type {
  ExtraFsxMount,
  FsxMountRef,
  RayJobCreatePayload,
  RayJobDetail,
  S3DatasetRef,
} from '../../api/types';
import {
  aggregateQuota,
  getWorkspaceQuota,
  getWorkspaceQuotaUsage,
} from '@/features/quota/api';
import {
  listSharedPVCs,
  type SharedPVCInfo,
} from '@/features/devinstance/api/client';
import {
  listWorkspaceS3,
  type WorkspaceS3Mount,
} from '@/features/workspace/api';
import {
  listResourceTemplates,
  type ResourceTemplateItem,
} from '@/api/resource-templates';
import type { Pool } from '@/api/resource-pool';
import { getSecretView } from '@/api/secret';
import LabelsField from '@/shared/ui/LabelsField';
import ScriptEditor from '@/features/training/components/CreateForm/ScriptEditor';
import PreviewSection from '@/features/training/components/CreateForm/PreviewSection';
import StorageSection from '@/features/training/components/CreateForm/StorageSection';
import ResourceSection, { HEAD_FIELDS, WORKER_FIELDS } from './ResourceSection';
import ImageField from './ImageField';

const DEFAULT_HEAD_IMAGE = 'rayproject/ray:2.9.0'; // head 落 CPU node → CPU 镜像
const DEFAULT_WORKER_IMAGE = 'rayproject/ray:2.9.0-gpu'; // worker 落 GPU node → gpu 镜像

interface FormValues {
  display_name: string;
  description?: string;
  head_image: string;
  worker_image: string;
  entry_script_path: string;
  worker_replicas: number;
  // head 资源 (协调节点, 默认 CPU 池)
  head_instance_type?: string;
  head_template_id?: string;
  head_gpu: number;
  head_cpu_cores: number;
  head_mem_gib: number;
  head_efa?: number;
  // worker 资源 (计算节点, 默认 GPU 池)
  worker_instance_type?: string;
  worker_template_id?: string;
  gpu_per_node: number;
  cpu_per_node_cores: number;
  memory_per_node_gib: number;
  efa_per_node?: number;
  max_run_hours: number;
  ttl_seconds_after_finished: number;
  backoff_limit: number;
  env_pairs: { key: string; value: string }[];
  env_secret_pairs?: { secret_key?: string }[];
  label_pairs: { key: string; value: string }[];
}

function buildPayload(
  values: FormValues,
  fsxChecked: string[],
  s3Checked: string[],
): RayJobCreatePayload {
  const env: Record<string, string> = {};
  for (const p of values.env_pairs || []) {
    if (p?.key) env[p.key.trim()] = (p.value ?? '').trim();
  }
  const envSecrets = (values.env_secret_pairs || [])
    .filter((p) => p?.secret_key)
    .map((p) => ({
      name: p.secret_key as string,
      secret_key: p.secret_key as string,
    }));
  const fsxMounts: FsxMountRef[] = fsxChecked.map((pvc_name) => ({ pvc_name }));
  const s3Datasets: S3DatasetRef[] = s3Checked.map((mount_id) => ({ mount_id }));
  return {
    // 不传 name: 后端从 display_name 派生, 传了会被 422 拒; 真名从创建响应读
    display_name: values.display_name.trim(),
    description: values.description?.trim() || null,
    head_image: (values.head_image ?? '').trim() || DEFAULT_HEAD_IMAGE,
    worker_image: (values.worker_image ?? '').trim() || DEFAULT_WORKER_IMAGE,
    fsx_mounts: fsxMounts,
    s3_datasets: s3Datasets,
    entry_script_path: (values.entry_script_path ?? '').trim(),
    worker_replicas: values.worker_replicas,
    head_instance_type: values.head_instance_type || '',
    head_gpu: values.head_gpu ?? 0,
    head_cpu_request_millicores: Math.round((values.head_cpu_cores ?? 0) * 1000),
    head_cpu_limit_millicores: Math.round((values.head_cpu_cores ?? 0) * 1000),
    head_memory_request_mib: Math.round((values.head_mem_gib ?? 0) * 1024),
    head_memory_limit_mib: Math.round((values.head_mem_gib ?? 0) * 1024),
    head_efa: values.head_efa || 0,
    worker_instance_type: values.worker_instance_type || '',
    gpu_per_node: values.gpu_per_node,
    cpu_request_millicores: Math.round((values.cpu_per_node_cores ?? 0) * 1000),
    cpu_limit_millicores: Math.round((values.cpu_per_node_cores ?? 0) * 1000),
    memory_request_mib: Math.round((values.memory_per_node_gib ?? 0) * 1024),
    memory_limit_mib: Math.round((values.memory_per_node_gib ?? 0) * 1024),
    efa_per_node: values.efa_per_node || 0,
    max_run_hours: values.max_run_hours,
    ttl_seconds_after_finished: values.ttl_seconds_after_finished,
    backoff_limit: values.backoff_limit,
    env,
    env_secrets: envSecrets,
    run_as_root: true, // 固定 root: Ray 镜像非 root 读不了 FSx (盘 gid), 平台默认 root 跑通
    labels: Object.fromEntries(
      (values.label_pairs || [])
        .filter((p) => p?.key?.trim())
        .map((p) => [p.key.trim(), (p.value ?? '').trim()]),
    ),
  };
}

// 克隆: RayJobDetail → 表单值 (照训练 mapDetailToFormValues)。name 由 BasicSection 派生。
function mapDetailToFormValues(d: RayJobDetail): Partial<FormValues> {
  return {
    display_name: `${d.display_name}-copy`,
    description: d.description ?? undefined,
    head_image: d.head_image,
    worker_image: d.worker_image,
    entry_script_path: d.entry_script_path ?? '',
    worker_replicas: d.worker_replicas,
    head_instance_type: d.head_instance_type || undefined,
    head_gpu: d.head_gpu ?? 0,
    head_cpu_cores: (d.head_cpu_request_millicores ?? 0) / 1000,
    head_mem_gib: (d.head_memory_request_mib ?? 0) / 1024,
    head_efa: d.head_efa ?? 0,
    worker_instance_type: d.worker_instance_type || undefined,
    gpu_per_node: d.gpu_per_node,
    cpu_per_node_cores: (d.cpu_request_millicores ?? 0) / 1000,
    memory_per_node_gib: (d.memory_request_mib ?? 0) / 1024,
    efa_per_node: d.efa_per_node ?? 0,
    max_run_hours: d.max_run_hours,
    ttl_seconds_after_finished: d.ttl_seconds_after_finished,
    backoff_limit: d.backoff_limit,
    env_pairs: Object.entries(d.env || {}).map(([key, value]) => ({
      key,
      value: String(value ?? ''),
    })),
    // env_secrets 克隆清空: secret 是原作者的, 克隆者重选自己的 key
    env_secret_pairs: (d.env_secrets || []).map(() => ({ secret_key: undefined })),
    label_pairs: Object.entries(d.labels || {}).map(([key, value]) => ({
      key,
      value: String(value ?? ''),
    })),
  };
}

export default function CreateForm() {
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation(['rayjob', 'common']);
  const [searchParams] = useSearchParams();
  const cloneFrom = searchParams.get('cloneFrom');
  const [form] = Form.useForm<FormValues>();
  const [submitting, setSubmitting] = useState(false);
  const [cloneLoading, setCloneLoading] = useState<boolean>(!!cloneFrom);

  const [quotaTotalGpu, setQuotaTotalGpu] = useState<number>(0);
  const [usageUsedGpu, setUsageUsedGpu] = useState<number>(-1);
  const [wsInstanceTypes, setWsInstanceTypes] = useState<string[]>([]);
  const [instTypePool, setInstTypePool] = useState<Record<string, Pool>>({});
  const [instTypeGpuSpec, setInstTypeGpuSpec] = useState<Record<string, string>>({});
  const [allTemplates, setAllTemplates] = useState<ResourceTemplateItem[]>([]);
  const [sharedPvcs, setSharedPvcs] = useState<SharedPVCInfo[] | null>(null);
  // 暂存克隆源的 FSx, 待授权列表到达后按权限筛 (clone effect 只跑一次)
  const [clonedFsxMounts, setClonedFsxMounts] = useState<ExtraFsxMount[] | null>(
    null,
  );
  const [wsS3Mounts, setWsS3Mounts] = useState<WorkspaceS3Mount[]>([]);
  const [fsxChecked, setFsxChecked] = useState<string[]>([]);
  const [s3Checked, setS3Checked] = useState<string[]>([]);
  const [secretKeys, setSecretKeys] = useState<string[]>([]);
  const [previewYamlText, setPreviewYamlText] = useState<string>('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [exampleOpen, setExampleOpen] = useState(false);
  // Ray 入口脚本示例 (FSx 上 .sh, entrypoint=bash <此>; 脚本里 ray.init() 接管集群)。
  // 注释随语言, 命令本体两种语言一致; 渲染时再翻译 (不放模块顶层)。
  const exampleScript = t('create.launch.exampleScript');

  useEffect(() => {
    if (!wsId) return;
    listResourceTemplates(wsId).then(setAllTemplates).catch(() => setAllTemplates([]));
    listSharedPVCs(wsId).then(setSharedPvcs).catch(() => setSharedPvcs([]));
    listWorkspaceS3(wsId).then(setWsS3Mounts).catch(() => setWsS3Mounts([]));
    getSecretView(wsId).then((v) => setSecretKeys(v.keys || [])).catch(() => setSecretKeys([]));
  }, [wsId]);

  // 一块盘对读写/只读用户是两个 pvc 名 (…-rw / …-ro), 权限不同就匹配不上 → 留空
  useEffect(() => {
    if (!clonedFsxMounts || sharedPvcs === null) return;
    const authed = new Map(sharedPvcs.map((p) => [p.name, p]));
    const kept = clonedFsxMounts.filter((m) => authed.has(m.pvc_name));
    const dropped = clonedFsxMounts.filter((m) => !authed.has(m.pvc_name));
    if (kept.length) setFsxChecked(kept.map((m) => m.pvc_name));
    if (dropped.length) {
      const why = dropped.map((m) => {
        const mine = sharedPvcs.find((p) => p.mount_path === m.mount_path);
        if (mine) {
          return t('create.messages.fsxNeed', {
            path: m.mount_path,
            need: m.read_only ? t('create.access.ro') : t('create.access.rw'),
            have: mine.access === 'ro' ? t('create.access.ro') : t('create.access.rw'),
          });
        }
        return t('create.messages.fsxNoAccess', { path: m.mount_path });
      });
      message.warning(
        t('create.messages.cloneFsxDropped', {
          count: dropped.length,
          details: why.join('; '),
        }),
        8,
      );
    }
    setClonedFsxMounts(null);
  }, [clonedFsxMounts, sharedPvcs, t]);

  useEffect(() => {
    if (!wsId) return;
    let cancelled = false;
    Promise.allSettled([getWorkspaceQuota(wsId), getWorkspaceQuotaUsage(wsId)]).then(
      ([q, u]) => {
        if (cancelled) return;
        if (q.status === 'fulfilled') {
          setQuotaTotalGpu(aggregateQuota(q.value.resources).totalAccelerators);
          const types = Array.from(
            new Set((q.value.resources ?? []).map((r) => r.instanceType).filter(Boolean)),
          );
          setWsInstanceTypes(types);
          const poolMap: Record<string, Pool> = {};
          const specMap: Record<string, string> = {};
          for (const r of q.value.resources ?? []) {
            if (r.instanceType) {
              poolMap[r.instanceType] = r.pool ?? 'cpu';
              if (r.gpuSpec) specMap[r.instanceType] = r.gpuSpec;
            }
          }
          setInstTypePool(poolMap);
          setInstTypeGpuSpec(specMap);
        }
        if (u.status === 'fulfilled') setUsageUsedGpu(u.value.totals.accelerators);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [wsId]);

  // 克隆: ?cloneFrom=<id> → 拉源配置预填 + 滚到预览
  useEffect(() => {
    if (!cloneFrom) return;
    let cancelled = false;
    (async () => {
      try {
        const d = await getRayJob(cloneFrom);
        if (cancelled) return;
        form.setFieldsValue(mapDetailToFormValues(d));
        try {
          const tpls = await listResourceTemplates(wsId);
          if (cancelled) return;
          // head + worker 各反查匹配模板 (按 gpu/cpu/mem 真值)
          const matchTpl = (gpu: number, cpuMilli: number, memMib: number) =>
            tpls.find(
              (tpl) =>
                tpl.resource.gpu === gpu &&
                tpl.resource.cpu_cores === cpuMilli / 1000 &&
                tpl.resource.mem_gib === memMib / 1024,
            );
          const headHit = matchTpl(d.head_gpu, d.head_cpu_request_millicores, d.head_memory_request_mib);
          const workerHit = matchTpl(d.gpu_per_node, d.cpu_request_millicores, d.memory_request_mib);
          if (headHit) form.setFieldValue('head_template_id', headHit.template_id);
          if (workerHit) form.setFieldValue('worker_template_id', workerHit.template_id);
          if (!headHit || !workerHit) {
            message.warning(t('create.messages.cloneTemplateChanged'));
          }
        } catch {
          /* 模板反查失败不阻塞 */
        }
        setClonedFsxMounts(d.extra_fsx_mounts ?? []);
      } catch (err) {
        if (cancelled) return;
        message.error(
          t('create.messages.cloneFetchFailed', {
            error: err instanceof ApiError ? err.message : String(err),
          }),
        );
      } finally {
        if (!cancelled) {
          setCloneLoading(false);
          setTimeout(
            () => document.getElementById('ray-preview')?.scrollIntoView({ behavior: 'smooth' }),
            150,
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cloneFrom]);

  const remainingGpu = useMemo(() => {
    if (usageUsedGpu < 0) return null;
    return Math.max(0, quotaTotalGpu - usageUsedGpu);
  }, [quotaTotalGpu, usageUsedGpu]);

  const watchedWorkerReplicas = Form.useWatch('worker_replicas', form);
  const watchedGpuPerNode = Form.useWatch('gpu_per_node', form);
  const requestedGpu = useMemo(
    () => (watchedWorkerReplicas ?? 1) * (watchedGpuPerNode ?? 0),
    [watchedWorkerReplicas, watchedGpuPerNode],
  );
  const gpuOverQuota = remainingGpu !== null && requestedGpu > remainingGpu;

  const fetchPreview = useCallback(async () => {
    setPreviewLoading(true);
    try {
      const values = form.getFieldsValue(true) as FormValues;
      const { yaml: text } = await previewRayJob(wsId, buildPayload(values, fsxChecked, s3Checked));
      setPreviewYamlText(text);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : (err as Error).message;
      setPreviewYamlText(t('create.yamlComments.renderFailed', { error: msg }));
    } finally {
      setPreviewLoading(false);
    }
  }, [form, wsId, fsxChecked, s3Checked, t]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      const detail = await createRayJob(wsId, buildPayload(values, fsxChecked, s3Checked));
      message.success(t('create.messages.submitted', { name: detail.k8s_cr_name }));
      navigate(`/workspaces/${wsId}/rayjob/${detail.id}`);
    } catch (err) {
      if (err && typeof err === 'object' && 'errorFields' in err) {
        const ef = (err as { errorFields?: Array<{ name: string[]; errors: string[] }> }).errorFields;
        const first = ef?.[0];
        message.error(
          t('create.messages.fieldInvalid', {
            field: first?.name?.join('.') ?? '?',
            error: first?.errors?.[0] ?? '',
          }),
        );
        return;
      }
      const msg = err instanceof ApiError ? err.message : (err as Error).message;
      message.error(t('create.messages.submitFailed', { error: msg }));
    } finally {
      setSubmitting(false);
    }
  };

  const initialValues: Partial<FormValues> = {
    display_name: '',
    head_image: DEFAULT_HEAD_IMAGE,
    worker_image: DEFAULT_WORKER_IMAGE,
    entry_script_path: '',
    worker_replicas: 1,
    head_gpu: 0,
    head_cpu_cores: 2,
    head_mem_gib: 8,
    head_efa: 0,
    gpu_per_node: 1,
    cpu_per_node_cores: 4,
    memory_per_node_gib: 16,
    efa_per_node: 0,
    max_run_hours: 24,
    ttl_seconds_after_finished: 3600,
    backoff_limit: 0,
    env_pairs: [],
    env_secret_pairs: [],
    label_pairs: [],
  };

  return (
    <ProCard bordered>
      <Spin spinning={cloneLoading} tip={t('create.loadingConfig')}>
        <Row gutter={24} wrap={false}>
          <Col flex="auto" style={{ minWidth: 0 }}>
            <Form<FormValues> form={form} layout="vertical" className="hp-create-form" initialValues={initialValues}>
              <div id="ray-basic">
                <Typography.Title level={5}>{t('create.sections.basic')}</Typography.Title>
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item
                      name="display_name"
                      label={t('create.basic.displayNameLabel')}
                      tooltip={t('create.basic.displayNameTooltip')}
                      rules={[
                        { required: true, message: t('create.basic.displayNameRequired') },
                        {
                          pattern: /^[a-z][a-z0-9-]{1,34}[a-z0-9]$/,
                          message: t('create.basic.displayNamePattern'),
                        },
                      ]}
                    >
                      <Input maxLength={36} showCount placeholder={t('create.basic.displayNamePlaceholder')} />
                    </Form.Item>
                  </Col>
                  <Col span={24}>
                    <Form.Item name="description" label={t('common:fields.description')}>
                      <Input.TextArea rows={2} maxLength={512} showCount placeholder={t('create.basic.descriptionPlaceholder')} />
                    </Form.Item>
                  </Col>
                  <Col span={24}>
                    <LabelsField />
                  </Col>
                </Row>
              </div>
              <Divider />

              <div id="ray-storage">
                <Typography.Title level={5}>{t('create.sections.storage')}</Typography.Title>
                <StorageSection
                  sharedPvcs={sharedPvcs}
                  fsxChecked={fsxChecked}
                  onFsxChange={setFsxChecked}
                  wsS3Mounts={wsS3Mounts}
                  s3Checked={s3Checked}
                  onS3Change={setS3Checked}
                />
              </div>
              <Divider />

              <div id="ray-resource">
                <Typography.Title level={5}>{t('create.image.headHeading')}</Typography.Title>
                <ImageField
                  wsId={wsId}
                  name="head_image"
                  label={t('create.image.headLabel')}
                  tooltip={t('create.image.headTooltip')}
                  placeholder={DEFAULT_HEAD_IMAGE}
                />
                <ResourceSection
                  fields={HEAD_FIELDS}
                  defaultPool="cpu"
                  wsInstanceTypes={wsInstanceTypes}
                  instTypePool={instTypePool}
                  instTypeGpuSpec={instTypeGpuSpec}
                  allTemplates={allTemplates}
                />
                <Divider dashed />

                <Typography.Title level={5}>{t('create.worker.heading')}</Typography.Title>
                <Row gutter={16} style={{ marginTop: 8, marginBottom: 8 }}>
                  <Col span={6}>
                    <Form.Item
                      name="worker_replicas"
                      label={t('create.worker.replicasLabel')}
                      tooltip={t('create.worker.replicasTooltip')}
                      rules={[{ required: true, message: t('create.worker.replicasRequired') }]}
                      style={{ marginBottom: 0 }}
                    >
                      <InputNumber min={1} max={64} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                </Row>
                <ImageField
                  wsId={wsId}
                  name="worker_image"
                  label={t('create.image.workerLabel')}
                  tooltip={t('create.image.workerTooltip')}
                  placeholder={DEFAULT_WORKER_IMAGE}
                />
                <ResourceSection
                  fields={WORKER_FIELDS}
                  defaultPool="gpu"
                  wsInstanceTypes={wsInstanceTypes}
                  instTypePool={instTypePool}
                  instTypeGpuSpec={instTypeGpuSpec}
                  allTemplates={allTemplates}
                />
                {remainingGpu !== null && (
                  <div style={{ fontSize: 12, marginTop: 8, color: gpuOverQuota ? '#f5222d' : '#999' }}>
                    {t('create.resource.quotaNeed', {
                      count: requestedGpu,
                      workers: t('spec.workerCount', { count: watchedWorkerReplicas ?? 1 }),
                      gpu: t('spec.gpuCount', { count: watchedGpuPerNode ?? 0 }),
                    })}
                    {t('create.resource.quotaRemaining', {
                      remaining: remainingGpu,
                      total: quotaTotalGpu,
                    })}
                    {gpuOverQuota && t('create.resource.quotaOver')}
                  </div>
                )}
              </div>
              <Divider />

              <div id="ray-launch">
                <Typography.Title level={5}>{t('create.sections.launch')}</Typography.Title>
                <Form.Item
                  name="entry_script_path"
                  label={t('create.launch.entryLabel')}
                  tooltip={<span>{t('create.launch.entryTooltip')}</span>}
                  rules={[{ required: true, message: t('create.launch.entryRequired') }]}
                  extra={
                    <Button type="link" style={{ padding: 0 }} onClick={() => setExampleOpen(true)}>
                      {t('create.launch.viewExample')}
                    </Button>
                  }
                >
                  <ScriptEditor height={190} />
                </Form.Item>

                <Drawer
                  title={t('create.launch.exampleTitle')}
                  width={760}
                  open={exampleOpen}
                  onClose={() => setExampleOpen(false)}
                >
                  <div style={{ marginBottom: 12, color: '#888', fontSize: 13, lineHeight: 1.6 }}>
                    {t('create.launch.exampleDesc')}
                  </div>
                  <ScriptEditor readOnly height="calc(100vh - 200px)" value={exampleScript} />
                </Drawer>

                <div style={{ fontWeight: 500, margin: '12px 0' }}>
                  {t('create.launch.envHeading')}
                  <Tooltip title={t('create.launch.envHelp')}>
                    <QuestionCircleOutlined style={{ color: '#999', marginLeft: 6 }} />
                  </Tooltip>
                </div>
                <Form.List name="env_pairs">
                  {(fields, { add, remove }) => (
                    <>
                      {fields.map(({ key, name, ...rest }) => (
                        <Row gutter={8} key={key} align="middle">
                          <Col span={10}>
                            <Form.Item {...rest} name={[name, 'key']} rules={[{ required: true, message: 'key' }]}>
                              <Input placeholder="key e.g. WANDB_PROJECT" />
                            </Form.Item>
                          </Col>
                          <Col span={12}>
                            <Form.Item {...rest} name={[name, 'value']}>
                              <Input placeholder="value" />
                            </Form.Item>
                          </Col>
                          <Col span={2}>
                            <MinusCircleOutlined onClick={() => remove(name)} style={{ fontSize: 18, color: '#999' }} />
                          </Col>
                        </Row>
                      ))}
                      <Button type="dashed" onClick={() => add({ key: '', value: '' })} icon={<PlusOutlined />} block>
                        {t('create.launch.envAdd')}
                      </Button>
                    </>
                  )}
                </Form.List>

                <div style={{ fontWeight: 500, margin: '12px 0' }}>
                  {t('create.launch.secretHeading')}
                  <Tooltip title={t('create.launch.secretHelp')}>
                    <QuestionCircleOutlined style={{ color: '#999', marginLeft: 6 }} />
                  </Tooltip>
                </div>
                <Form.List name="env_secret_pairs">
                  {(fields, { add, remove }) => (
                    <>
                      {fields.map(({ key, name, ...rest }) => (
                        <Row gutter={8} key={key} align="middle">
                          <Col span={22}>
                            <Form.Item {...rest} name={[name, 'secret_key']} rules={[{ required: true, message: t('create.launch.secretKeyRequired') }]}>
                              <Select
                                placeholder={t('create.launch.secretPlaceholder')}
                                options={secretKeys.map((k) => ({ label: k, value: k }))}
                                notFoundContent={t('create.launch.secretEmpty')}
                              />
                            </Form.Item>
                          </Col>
                          <Col span={2}>
                            <MinusCircleOutlined onClick={() => remove(name)} style={{ fontSize: 18, color: '#999' }} />
                          </Col>
                        </Row>
                      ))}
                      <Button type="dashed" onClick={() => add({ secret_key: undefined })} icon={<PlusOutlined />} block>
                        {t('create.launch.secretAdd')}
                      </Button>
                    </>
                  )}
                </Form.List>
              </div>
              <Divider />

              <div id="ray-policy">
                <Typography.Title level={5}>{t('create.sections.policy')}</Typography.Title>
                <Row gutter={16}>
                  <Col span={8}>
                    <Form.Item
                      name="max_run_hours"
                      label={t('create.policy.maxRunLabel')}
                      tooltip={t('create.policy.maxRunTooltip')}
                    >
                      <InputNumber min={1} max={720} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col span={8}>
                    <Form.Item
                      name="ttl_seconds_after_finished"
                      label={t('create.policy.ttlLabel')}
                      tooltip={t('create.policy.ttlTooltip')}
                    >
                      <InputNumber min={0} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col span={8}>
                    <Form.Item
                      name="backoff_limit"
                      label={t('create.policy.retriesLabel')}
                      tooltip={t('create.policy.retriesTooltip')}
                    >
                      <InputNumber min={0} max={10} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                </Row>
              </div>
              <Divider />

              <div id="ray-preview">
                <Typography.Title level={5}>{t('create.sections.preview')}</Typography.Title>
                <PreviewSection
                  previewYaml={previewYamlText}
                  previewLoading={previewLoading}
                  onRefreshPreview={() => void fetchPreview()}
                  showRunPolicy={false}
                />
              </div>

              <Space style={{ marginTop: 24 }}>
                <Button type="primary" icon={<RocketOutlined />} loading={submitting} onClick={handleSubmit}>
                  {t('create.submit')}
                </Button>
                <Button onClick={() => navigate(`/workspaces/${wsId}/rayjob`)}>
                  {t('common:actions.cancel')}
                </Button>
              </Space>
            </Form>
          </Col>

          <Col flex="0 0 180px">
            <Anchor
              affix
              offsetTop={80}
              items={(
                [
                  ['basic', t('create.sections.basic')],
                  ['image', t('create.sections.image')],
                  ['storage', t('create.sections.storage')],
                  ['resource', t('create.sections.resource')],
                  ['launch', t('create.sections.launch')],
                  ['policy', t('create.sections.policy')],
                  ['preview', t('create.sections.preview')],
                ] as const
              ).map(([key, label]) => ({
                key,
                href: `#ray-${key}`,
                title: <span style={{ display: 'block', padding: '6px 0' }}>{label}</span>,
              }))}
            />
          </Col>
        </Row>
      </Spin>
    </ProCard>
  );
}
