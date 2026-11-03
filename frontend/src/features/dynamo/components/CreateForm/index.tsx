import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Anchor, Button, Col, Divider, Form, Row, Space, Spin, Typography, message } from 'antd';
import { RocketOutlined } from '@ant-design/icons';
import { ProCard } from '@ant-design/pro-components';
import { ApiError } from '@/shared/api';
import i18n from '@/shared/i18n';
import { createDynamo, getDynamo, previewDynamo } from '../../api/client';
import type {
  DynamoCreatePayload,
  DynamoDetail,
  DynamoModelSourceType,
} from '../../api/types';
import {
  listWorkspaceFsx,
  listWorkspaceS3,
  type WorkspaceFsxMount,
  type WorkspaceS3Mount,
} from '@/features/workspace/api';
import { listSharedPVCs, type SharedPVCInfo } from '@/features/devinstance/api/client';
import {
  aggregateQuota,
  getWorkspaceQuota,
  getWorkspaceQuotaUsage,
} from '@/features/quota/api';
import { listResourceTemplates, type ResourceTemplateItem } from '@/api/resource-templates';
import type { Pool } from '@/api/resource-pool';
import BasicSection from './BasicSection';
import ImageSection from './ImageSection';
import ModelSourceSection, { type AuthedFsxMount } from './ModelSourceSection';
import InstanceSection from './InstanceSection';
import CommandSection from './CommandSection';
import AdvancedSection from './AdvancedSection';

const DEFAULT_IMAGE = 'nvcr.io/nvidia/ai-dynamo/sglang-runtime:1.2.1-efa-amd64';

// Dynamo sglang 单脚本启动 (exec 接管主进程; --model-path 写模型在 FSx 里的绝对路径,
// = 选中 FSx 挂载点 + 盘内模型目录, 如 /fsx/team-a-data/models/qwen2.5-0.5b; tp/ep 在此)
// 代码本体两种语言逐字节一致, 只有尖括号占位符里的说明随语言。
// 函数(非模块级常量): 调用时才取翻译, 避免模块加载期求值。
function defaultLaunchScript(): string {
  const fsxMount = i18n.t('create.launch.script.fsxMount', { ns: 'dynamo' });
  const modelDir = i18n.t('create.launch.script.modelDir', { ns: 'dynamo' });
  const modelName = i18n.t('create.launch.script.modelName', { ns: 'dynamo' });
  return (
    'exec python3 -m dynamo.sglang \\\n' +
    `  --model-path <${fsxMount}>/models/<${modelDir}> \\\n` +
    `  --served-model-name <${modelName}> \\\n` +
    '  --tp-size 8 \\\n' +
    '  --ep-size 8 \\\n' +
    '  --trust-remote-code \\\n' +
    '  --skip-tokenizer-init \\\n' +
    '  --host 0.0.0.0'
  );
}

interface FormValues {
  name: string;
  display_name: string;
  description?: string;
  image: string;
  model_source_type: DynamoModelSourceType;
  fsx_pvc_name?: string;
  s3_mount_id?: string;
  s3_model_location?: string;
  node_count: number;
  replicas: number;
  launch_script: string;
  instance_type: string;
  template_id?: string;
  gpu_per_worker: number;
  cpu_cores: number;
  mem_gib: number;
  efa_per_worker: number;
  label_pairs: { key: string; value: string }[];
}

function buildPayload(v: FormValues, s3Mounts: WorkspaceS3Mount[]): DynamoCreatePayload {
  const s3Mount = s3Mounts.find((m) => m.mount_id === v.s3_mount_id);
  const s3 =
    v.model_source_type === 's3' && s3Mount && v.s3_model_location
      ? {
          bucket_name: s3Mount.bucket_name,
          region: s3Mount.region || 'us-west-2',
          model_location: v.s3_model_location,
          prefetch_enabled: true,
        }
      : null;
  return {
    name: v.name,
    display_name: v.display_name,
    description: v.description || null,
    backend_framework: 'sglang',
    image: (v.image || '').trim() || DEFAULT_IMAGE,
    model_source_type: v.model_source_type,
    fsx_pvc_name: v.model_source_type === 'fsx' ? v.fsx_pvc_name || null : null,
    s3,
    node_count: v.node_count,
    replicas: v.replicas,
    launch_script: (v.launch_script || '').trim(),
    instance_type: v.instance_type,
    gpu_per_worker: v.gpu_per_worker,
    cpu_request_millicores: Math.round((v.cpu_cores ?? 0) * 1000),
    cpu_limit_millicores: Math.round((v.cpu_cores ?? 0) * 1000),
    memory_request_mib: Math.round((v.mem_gib ?? 0) * 1024),
    memory_limit_mib: Math.round((v.mem_gib ?? 0) * 1024),
    efa_per_worker: v.efa_per_worker ?? 0,
    run_as_root: true, // 固定 root: dynamo 镜像 uid=1000 读不了 FSx, 平台默认 root 跑通

    labels: Object.fromEntries(
      (v.label_pairs || [])
        .filter((p) => p?.key?.trim())
        .map((p) => [p.key.trim(), (p.value ?? '').trim()]),
    ),
  };
}

// 克隆: DynamoDetail → 表单值 (照推理 mapDetailToFormValues)。
// name/display_name 加 -copy; fsx_pvc_name/s3_mount_id 在 clone effect 内按值反查回填;
// 资源 (gpu/cpu/mem) 用真值, template_id 在 effect 内反查匹配。
function mapDetailToFormValues(d: DynamoDetail): Partial<FormValues> {
  return {
    // 任务名不在此设: 由 BasicSection 的 useWatch 从 display_name 自动派生
    // (sanitize(显示名)+本页随机后缀), 保证唯一且改显示名不重掷随机。
    display_name: `${d.display_name}-copy`,
    description: d.description ?? undefined,
    image: d.image,
    model_source_type: (d.model_source_type as DynamoModelSourceType) || 'fsx',
    fsx_pvc_name: d.fsx_pvc_name ?? undefined,
    s3_model_location: d.s3?.model_location,
    node_count: d.node_count,
    replicas: d.replicas,
    launch_script: d.launch_script || '',
    instance_type: d.instance_type,
    gpu_per_worker: d.gpu_per_worker,
    cpu_cores: (d.cpu_request_millicores ?? 0) / 1000,
    mem_gib: (d.memory_request_mib ?? 0) / 1024,
    efa_per_worker: d.efa_per_worker,
    label_pairs: Object.entries(d.labels || {}).map(([key, value]) => ({
      key,
      value: String(value ?? ''),
    })),
  };
}

export default function CreateForm() {
  const { t } = useTranslation(['dynamo', 'common']);
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const cloneFrom = searchParams.get('cloneFrom');
  const [form] = Form.useForm<FormValues>();
  const [submitting, setSubmitting] = useState(false);
  const [cloneLoading, setCloneLoading] = useState<boolean>(!!cloneFrom);
  const [previewYaml, setPreviewYaml] = useState('');
  const [fsxMounts, setFsxMounts] = useState<WorkspaceFsxMount[] | null>(null);
  const [authedPvcs, setAuthedPvcs] = useState<SharedPVCInfo[] | null>(null);
  const [wsS3Mounts, setWsS3Mounts] = useState<WorkspaceS3Mount[] | null>(null);
  const [wsInstanceTypes, setWsInstanceTypes] = useState<string[]>([]);
  const [instTypePool, setInstTypePool] = useState<Record<string, Pool>>({});
  const [instTypeGpuSpec, setInstTypeGpuSpec] = useState<Record<string, string>>({});
  const [quotaTotalGpu, setQuotaTotalGpu] = useState<number>(0);
  const [usageUsedGpu, setUsageUsedGpu] = useState<number>(-1);
  const [allTemplates, setAllTemplates] = useState<ResourceTemplateItem[]>([]);
  // 模板加载完标志 (区分"加载中"vs"加载完但 ws 无模板", 克隆 guard 用)
  const [templatesLoaded, setTemplatesLoaded] = useState(false);

  useEffect(() => {
    if (!wsId) return;
    let cancelled = false;
    Promise.allSettled([getWorkspaceQuota(wsId), getWorkspaceQuotaUsage(wsId)]).then(([q, u]) => {
      if (cancelled) return;
      if (q.status === 'fulfilled') {
        setQuotaTotalGpu(aggregateQuota(q.value.resources).totalAccelerators);
        const poolMap: Record<string, Pool> = {};
        const specMap: Record<string, string> = {};
        const types: string[] = [];
        for (const r of q.value.resources ?? []) {
          if (r.instanceType) {
            types.push(r.instanceType);
            poolMap[r.instanceType] = r.pool ?? 'cpu';
            if (r.gpuSpec) specMap[r.instanceType] = r.gpuSpec;
          }
        }
        setWsInstanceTypes(Array.from(new Set(types)));
        setInstTypePool(poolMap);
        setInstTypeGpuSpec(specMap);
      }
      if (u.status === 'fulfilled') setUsageUsedGpu(u.value.totals.accelerators);
    });
    return () => {
      cancelled = true;
    };
  }, [wsId]);

  // 依赖只放 wsId: 四个请求由内部守卫 (templatesLoaded / `=== null`) 保证只在未加载时发一次。
  // 若把 fsxMounts 等放进依赖, 它们 setState 后会反复触发 effect 重跑 (照推理 CreateForm)。
  useEffect(() => {
    if (!wsId) return;
    if (!templatesLoaded) {
      listResourceTemplates(wsId)
        .then(setAllTemplates)
        .catch(() => setAllTemplates([]))
        .finally(() => setTemplatesLoaded(true));
    }
    if (fsxMounts === null) listWorkspaceFsx(wsId).then(setFsxMounts).catch(() => setFsxMounts([]));
    if (authedPvcs === null) listSharedPVCs(wsId).then(setAuthedPvcs).catch(() => setAuthedPvcs([]));
    if (wsS3Mounts === null) listWorkspaceS3(wsId).then(setWsS3Mounts).catch(() => setWsS3Mounts([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId]);

  const authedFsxMounts: AuthedFsxMount[] = useMemo(() => {
    if (!fsxMounts || !authedPvcs) return [];
    const byName = new Map(authedPvcs.map((p) => [p.name, p]));
    const allowed = new Set(authedPvcs.map((p) => p.name).filter(Boolean) as string[]);
    return fsxMounts
      .filter(
        (m) =>
          (m.pvc_name_rw && allowed.has(m.pvc_name_rw)) ||
          (m.pvc_name_ro && allowed.has(m.pvc_name_ro)) ||
          (m.pvc_name && allowed.has(m.pvc_name)),
      )
      .map((m) => {
        const rwPvc = m.pvc_name_rw && allowed.has(m.pvc_name_rw) ? m.pvc_name_rw : null;
        const matched =
          (rwPvc && byName.get(rwPvc)) ||
          (m.pvc_name_ro && byName.get(m.pvc_name_ro)) ||
          (m.pvc_name && byName.get(m.pvc_name)) ||
          undefined;
        return {
          ...m,
          access: (rwPvc ? 'rw' : matched?.access || 'ro') as 'ro' | 'rw',
          isPrimary: matched?.is_primary ?? false,
        };
      });
  }, [fsxMounts, authedPvcs]);

  // 克隆 (?cloneFrom=<id>, 照推理): 拉源详情 → 预填 → 资源模板反查 → S3 mount 反查。
  // guard ref 只跑一次 (依赖 allTemplates 引用变化会重跑, 会覆盖用户已填值)。
  // fsx 用 pvc_name 直接匹配 (dynamo 存的就是 pvc_name, 无需 filesystem_id 反推)。
  const clonePrefilled = useRef(false);
  useEffect(() => {
    if (!cloneFrom) return;
    // 用 templatesLoaded 而非 !allTemplates.length: ws 无模板时 [] 分不清"加载中"vs"加载完空"。
    if (!templatesLoaded) return;
    if (wsS3Mounts === null) return;
    if (clonePrefilled.current) return;
    clonePrefilled.current = true;
    let cancelled = false;
    (async () => {
      try {
        const d = await getDynamo(cloneFrom);
        // 不 early-return on cancelled: 依赖加载中会变触发 cleanup 置 cancelled, 这里 return
        // 会跳过唯一一次预填。clonePrefilled 已保证只进一次 IIFE, 预填幂等, 直接做。
        form.setFieldsValue(mapDetailToFormValues(d));

        // S3 单选: 按 bucket_name 反查挂载源 mount_id 回填
        if (d.model_source_type === 's3' && d.s3) {
          const sm = (wsS3Mounts ?? []).find((x) => x.bucket_name === d.s3?.bucket_name);
          if (sm) form.setFieldValue('s3_mount_id', sm.mount_id);
          else message.warning(t('create.messages.cloneS3Missing'));
        }

        // 资源模板反查: gpu/cpu/mem 真值匹配已加载的模板 → 回填 template_id
        const cpuCores = (d.cpu_request_millicores ?? 0) / 1000;
        const memGib = (d.memory_request_mib ?? 0) / 1024;
        const hit = allTemplates.find(
          (tpl) =>
            tpl.resource.gpu === d.gpu_per_worker &&
            tpl.resource.cpu_cores === cpuCores &&
            tpl.resource.mem_gib === memGib,
        );
        if (hit) form.setFieldValue('template_id', hit.template_id);
        else message.warning(t('create.messages.cloneTemplateChanged'));
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof ApiError ? err.message : String(err);
        message.error(t('create.messages.cloneFetchFailed', { error: msg }));
      } finally {
        // loading 无条件关 (即便 cancelled): 否则依赖变化触发的 cleanup 置 cancelled 后会永转。
        setCloneLoading(false);
        if (!cancelled) {
          setTimeout(
            () => document.getElementById('dyn-preview')?.scrollIntoView({ behavior: 'smooth' }),
            150,
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cloneFrom, templatesLoaded, wsS3Mounts]);

  const modelSourceType = Form.useWatch('model_source_type', form);
  const watchedNodeCount = Form.useWatch('node_count', form);
  const watchedReplicas = Form.useWatch('replicas', form);
  const watchedGpuPerWorker = Form.useWatch('gpu_per_worker', form);
  const requestedGpu = useMemo(
    () => (watchedReplicas ?? 1) * (watchedNodeCount ?? 1) * (watchedGpuPerWorker ?? 0),
    [watchedReplicas, watchedNodeCount, watchedGpuPerWorker],
  );
  const remainingGpu = useMemo(
    () => (usageUsedGpu < 0 ? null : Math.max(0, quotaTotalGpu - usageUsedGpu)),
    [quotaTotalGpu, usageUsedGpu],
  );
  const gpuOverQuota = remainingGpu !== null && requestedGpu > remainingGpu;

  const buildPreview = async () => {
    let v: FormValues;
    try {
      v = await form.validateFields();
    } catch {
      setPreviewYaml(t('create.messages.fillRequiredYaml'));
      message.warning(t('create.messages.fillRequiredWarn'));
      return;
    }
    setPreviewYaml(t('create.messages.rendering'));
    try {
      const { yaml } = await previewDynamo(wsId, buildPayload(v, wsS3Mounts ?? []));
      setPreviewYaml(yaml);
    } catch (err) {
      const msg = err instanceof ApiError ? `${err.status} ${err.message}` : String(err);
      setPreviewYaml(t('create.messages.renderFailed', { error: msg }));
    }
  };

  const onSubmit = async () => {
    try {
      const v = await form.validateFields();
      setSubmitting(true);
      const detail = await createDynamo(wsId, buildPayload(v, wsS3Mounts ?? []));
      message.success(t('create.messages.created'));
      navigate(`/workspaces/${wsId}/dynamo/${detail.id}`);
    } catch (err) {
      if ((err as { errorFields?: unknown }).errorFields) return;
      const msg = err instanceof Error ? err.message : String(err);
      message.error(t('create.messages.createFailed', { error: msg }));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ProCard bordered>
      <Spin spinning={cloneLoading} tip={t('create.loadingConfig')}>
      <Row gutter={24} wrap={false}>
        <Col flex="auto" style={{ minWidth: 0 }}>
          <Form
            form={form}
            layout="vertical"
            className="hp-create-form"
            initialValues={{
              image: DEFAULT_IMAGE,
              model_source_type: 'fsx',
              node_count: 1,
              replicas: 1,
              launch_script: defaultLaunchScript(),
              gpu_per_worker: 1,
              cpu_cores: 8,
              mem_gib: 32,
              efa_per_worker: 0,
              label_pairs: [],
            }}
          >
            <div id="dyn-basic">
              <Typography.Title level={5}>{t('create.sections.basic')}</Typography.Title>
              <BasicSection />
            </div>
            <Divider />
            <div id="dyn-image">
              <Typography.Title level={5}>{t('create.sections.image')}</Typography.Title>
              <ImageSection wsId={wsId} />
            </div>
            <Divider />
            <div id="dyn-model">
              <Typography.Title level={5}>{t('create.sections.model')}</Typography.Title>
              <ModelSourceSection
                modelSourceType={modelSourceType ?? 'fsx'}
                authedFsxMounts={authedFsxMounts}
                authedPvcs={authedPvcs}
                fsxMounts={fsxMounts}
                wsS3Mounts={wsS3Mounts}
              />
            </div>
            <Divider />
            <div id="dyn-instance">
              <Typography.Title level={5}>{t('create.sections.resource')}</Typography.Title>
              <InstanceSection
                wsInstanceTypes={wsInstanceTypes}
                instTypePool={instTypePool}
                instTypeGpuSpec={instTypeGpuSpec}
                allTemplates={allTemplates}
                remainingGpu={remainingGpu}
                quotaTotalGpu={quotaTotalGpu}
                requestedGpu={requestedGpu}
                watchedNodeCount={watchedNodeCount}
                watchedReplicas={watchedReplicas}
                watchedGpuPerWorker={watchedGpuPerWorker}
                gpuOverQuota={gpuOverQuota}
              />
            </div>
            <Divider />
            <div id="dyn-command">
              <Typography.Title level={5}>{t('create.sections.launch')}</Typography.Title>
              <CommandSection />
            </div>
            <Divider />
            <div id="dyn-preview">
              <Typography.Title level={5}>{t('create.sections.preview')}</Typography.Title>
              <AdvancedSection previewYaml={previewYaml} onPreview={buildPreview} />
            </div>

            <Space style={{ marginTop: 24 }}>
              <Button type="primary" icon={<RocketOutlined />} loading={submitting} onClick={onSubmit}>
                {t('common:actions.submit')}
              </Button>
              <Button onClick={() => navigate(`/workspaces/${wsId}/dynamo`)}>
                {t('common:actions.cancel')}
              </Button>
            </Space>
          </Form>
        </Col>

        <Col flex="0 0 160px">
          <Anchor
            affix
            offsetTop={80}
            items={[
              ['basic', t('create.sections.basic')],
              ['image', t('create.sections.image')],
              ['model', t('create.sections.model')],
              ['instance', t('create.sections.resource')],
              ['command', t('create.sections.launch')],
              ['preview', t('create.sections.preview')],
            ].map(([key, label]) => ({
              key,
              href: `#dyn-${key}`,
              title: <span style={{ display: 'block', padding: '6px 0' }}>{label}</span>,
            }))}
          />
        </Col>
      </Row>
      </Spin>
    </ProCard>
  );
}
