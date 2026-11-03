import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Anchor, Button, Col, Divider, Form, Row, Space, Spin, Typography, message } from 'antd';
import { RocketOutlined } from '@ant-design/icons';
import { ProCard } from '@ant-design/pro-components';
import { ApiError } from '@/shared/api';
import i18n from '@/shared/i18n';
import { createLlmd, getLlmd, previewLlmd } from '../../api/client';
import type {
  LlmdCreatePayload,
  LlmdDetail,
  LlmdModelSourceType,
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
import type { Pool } from '@/api/resource-pool';
import { listResourceTemplates, type ResourceTemplateItem } from '@/api/resource-templates';
import BasicSection from './BasicSection';
import GatewaySection from './GatewaySection';
import ImageSection from './ImageSection';
import ModelSourceSection, { type AuthedFsxMount } from './ModelSourceSection';
import InstanceSection from './InstanceSection';
import CommandSection from './CommandSection';
import AdvancedSection from './AdvancedSection';

const DEFAULT_GATEWAY_IMAGE = 'lmsysorg/sgl-model-gateway:latest';
const DEFAULT_SGLANG_IMAGE = 'lmsysorg/sglang:v0.5.13.post1';

// gateway router 调优参数默认值 (一行一个, 用户可改; 含 --policy)。结构性参数
// (--service-discovery/--selector/--port/--prometheus 等) 后端拼死, 不在此。
const DEFAULT_GATEWAY_ARGS = [
  '--policy=cache_aware',
  '--cache-threshold=0.3',
  '--balance-abs-threshold=64',
  '--balance-rel-threshold=1.5',
  '--eviction-interval-secs=120',
  '--max-concurrent-requests=256',
  '--queue-size=128',
  '--queue-timeout-secs=60',
  '--request-timeout-secs=600',
  '--retry-max-retries=3',
  '--cb-failure-threshold=5',
  '--cb-timeout-duration-secs=30',
  '--health-check-interval-secs=15',
  '--health-check-timeout-secs=5',
  '--log-level=info',
].join('\n');

// sglang 启动脚本默认值 (整段 sh -c 跑; LWS 组网占位符用 shell 形式 $LWS_* — 别写
// $(LWS_*), sh -c 下 $() 是命令替换会挂)。
// --model-path: FSx 挂到你开发机同样路径, 写完整绝对路径 (如 /fsx/team-a-data/models/qwen2.5-0.5b);
//   S3 挂到 /model, 写 /model/<prefix 下相对路径>。
// 代码本体两种语言逐字节一致, 只有尖括号占位符里的说明随语言。
// 函数(非模块级常量): 调用时才取翻译, 避免模块加载期求值。
function defaultLaunchScript(): string {
  const fsxMount = i18n.t('create.launch.script.fsxMount', { ns: 'llmd' });
  const modelDir = i18n.t('create.launch.script.modelDir', { ns: 'llmd' });
  const modelName = i18n.t('create.launch.script.modelName', { ns: 'llmd' });
  return [
    'exec python3 -m sglang.launch_server \\',
    `  --model-path <${fsxMount}>/models/<${modelDir}> \\`,
    `  --served-model-name <${modelName}> \\`,
    '  --tp-size 2 \\',
    '  --mem-fraction-static 0.85 \\',
    '  --dist-init-addr $LWS_LEADER_ADDRESS:20000 \\',
    '  --nnodes $LWS_GROUP_SIZE \\',
    '  --node-rank $LWS_WORKER_INDEX \\',
    '  --host 0.0.0.0 \\',
    '  --port 8000 \\',
    '  --trust-remote-code \\',
    '  --enable-metrics',
  ].join('\n');
}

interface FormValues {
  // 表单无任务名字段: 后端从 display_name 派生
  display_name: string;
  description?: string;
  model_source_type: LlmdModelSourceType;
  model_pvc?: string;
  s3_bucket?: string;
  s3_prefix?: string;
  launch_script: string;
  gpu_instance_type: string;
  gateway_instance_type: string;
  replicas: number;
  nodes_per_replica: number;
  // 资源模板选中 (前端联动) + 模板带出的隐藏真值
  template_id?: string;
  gpu_per_pod: number;
  efa_per_pod: number;
  cpu_request_millicores: number;
  cpu_limit_millicores: number;
  memory_request_mib: number;
  memory_limit_mib: number;
  gateway_image: string;
  sglang_image: string;
  gateway_replicas: number;
  gateway_extra_args: string; // 多行文本, 提交时 split 成 list
  // gateway CPU 池资源模板选中 (前端联动) + 模板带出的隐藏真值
  gateway_template_id?: string;
  gateway_cpu_request_millicores: number;
  gateway_cpu_limit_millicores: number;
  gateway_memory_request_mib: number;
  gateway_memory_limit_mib: number;
  expose_alb: boolean;
  label_pairs: { key: string; value: string }[];
}

function buildPayload(v: FormValues): LlmdCreatePayload {
  return {
    display_name: v.display_name,
    description: v.description || null,
    model_source_type: v.model_source_type,
    model_pvc: v.model_source_type === 'fsx' ? v.model_pvc || null : null,
    s3_bucket: v.model_source_type === 's3' ? v.s3_bucket || null : null,
    s3_prefix: v.model_source_type === 's3' ? (v.s3_prefix || '').trim() || null : null,
    // 逐行去尾部空格: 续行 `\` 后混空格 → 不续行, 注入空参数致 sglang 崩
    launch_script: (v.launch_script || '')
      .split('\n')
      .map((line) => line.replace(/\s+$/, ''))
      .join('\n')
      .trim(),
    gpu_instance_type: v.gpu_instance_type,
    gateway_instance_type: v.gateway_instance_type,
    replicas: v.replicas,
    nodes_per_replica: v.nodes_per_replica,
    gpu_per_pod: v.gpu_per_pod,
    efa_per_pod: v.efa_per_pod ?? 0,
    cpu_request_millicores: v.cpu_request_millicores,
    cpu_limit_millicores: v.cpu_limit_millicores,
    memory_request_mib: v.memory_request_mib,
    memory_limit_mib: v.memory_limit_mib,
    gateway_image: (v.gateway_image || '').trim() || DEFAULT_GATEWAY_IMAGE,
    sglang_image: (v.sglang_image || '').trim() || DEFAULT_SGLANG_IMAGE,
    gateway_replicas: v.gateway_replicas,
    // 多行文本 → list[str] (一行一参数, 去空行)
    gateway_extra_args: (v.gateway_extra_args || '')
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean),
    gateway_cpu_request_millicores: v.gateway_cpu_request_millicores,
    gateway_cpu_limit_millicores: v.gateway_cpu_limit_millicores,
    gateway_memory_request_mib: v.gateway_memory_request_mib,
    gateway_memory_limit_mib: v.gateway_memory_limit_mib,
    expose_alb: !!v.expose_alb,
    labels: Object.fromEntries(
      (v.label_pairs || [])
        .filter((p) => p?.key?.trim())
        .map((p) => [p.key.trim(), (p.value ?? '').trim()]),
    ),
  };
}

/** 克隆名 = 原名 + '-copy', 超 20 就先截断 (并去掉截断留下的尾部 '-')。 */
function cloneDisplayName(src: string): string {
  const SUFFIX = '-copy';
  const MAX = 20;
  const naive = `${src}${SUFFIX}`;
  if (naive.length <= MAX) return naive;
  return `${src.slice(0, MAX - SUFFIX.length).replace(/-+$/, '')}${SUFFIX}`;
}

// 克隆: LlmdDetail → 表单值。model_pvc 不在此回填 (要按克隆者权限筛, 见 clone effect)。
function mapDetailToFormValues(d: LlmdDetail): Partial<FormValues> {
  return {
    display_name: cloneDisplayName(d.display_name),
    description: d.description ?? undefined,
    model_source_type: (d.model_source_type as LlmdModelSourceType) || 'fsx',
    s3_bucket: d.s3_bucket ?? undefined,
    s3_prefix: d.s3_prefix ?? undefined,
    launch_script: d.launch_script || defaultLaunchScript(),
    gpu_instance_type: d.gpu_instance_type,
    gateway_instance_type: d.gateway_instance_type || d.gpu_instance_type,
    replicas: d.replicas,
    nodes_per_replica: d.nodes_per_replica,
    // template_id 不回填 (克隆时由 InstanceSection 按池默认最小模板重选); cpu/mem 带回作兜底
    gpu_per_pod: d.gpu_per_pod,
    efa_per_pod: d.efa_per_pod,
    cpu_request_millicores: d.cpu_request_millicores,
    cpu_limit_millicores: d.cpu_limit_millicores,
    memory_request_mib: d.memory_request_mib,
    memory_limit_mib: d.memory_limit_mib,
    gateway_image: d.gateway_image,
    sglang_image: d.sglang_image,
    gateway_replicas: d.gateway_replicas ?? 1,
    expose_alb: !!d.expose_alb,   // 克隆保留原实例的 ALB 选择
    gateway_extra_args: (d.gateway_extra_args ?? []).join('\n') || DEFAULT_GATEWAY_ARGS,
    // gateway_template_id 不回填 (克隆时由 GatewaySection 按 CPU 池默认最小模板重选); cpu/mem 带回兜底
    gateway_cpu_request_millicores: d.gateway_cpu_request_millicores,
    gateway_cpu_limit_millicores: d.gateway_cpu_limit_millicores,
    gateway_memory_request_mib: d.gateway_memory_request_mib,
    gateway_memory_limit_mib: d.gateway_memory_limit_mib,
    label_pairs: Object.entries(d.labels || {}).map(([key, value]) => ({
      key,
      value: String(value ?? ''),
    })),
  };
}

export default function CreateForm() {
  const { t } = useTranslation(['llmd', 'common']);
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
  const [templatesLoaded, setTemplatesLoaded] = useState(false);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [mountsLoading, setMountsLoading] = useState(false);

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

  // 挂载源刷新: 授权 FSx (shared-pvcs) + ws fsx mount + ws S3。
  // 抽成 useCallback 供模型源 FSx/S3 右侧刷新按钮调用; 与首次加载 effect 复用。
  // 不加 `=== null` 守卫: 刷新按钮就是要强制重发 (别处新挂载后即时可选)。
  const reloadMounts = useCallback(() => {
    if (!wsId) return;
    setMountsLoading(true);
    Promise.allSettled([
      listWorkspaceFsx(wsId),
      listSharedPVCs(wsId),
      listWorkspaceS3(wsId),
    ])
      .then(([fsx, pvcs, s3]) => {
        setFsxMounts(fsx.status === 'fulfilled' ? fsx.value : []);
        setAuthedPvcs(pvcs.status === 'fulfilled' ? pvcs.value : []);
        setWsS3Mounts(s3.status === 'fulfilled' ? s3.value : []);
      })
      .finally(() => setMountsLoading(false));
  }, [wsId]);

  // 资源模板刷新: worker/gateway 两处刷新按钮共用 (admin 新建模板后即时可选)。
  const refreshTemplates = useCallback(() => {
    if (!wsId) return;
    setTemplatesLoading(true);
    listResourceTemplates(wsId)
      .then(setAllTemplates)
      .catch(() => setAllTemplates([]))
      .finally(() => {
        setTemplatesLoaded(true);
        setTemplatesLoading(false);
      });
  }, [wsId]);

  // 首次加载 (依赖 reloadMounts/refreshTemplates, 只随 wsId 变;
  // 慢请求 fsx 期间的重渲染不会重发, 因回调引用不变)。
  useEffect(() => {
    reloadMounts();
  }, [reloadMounts]);
  useEffect(() => {
    refreshTemplates();
  }, [refreshTemplates]);

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

  // 克隆 (?cloneFrom=<id>): 拉源详情 → 预填 + 资源模板反查。guard ref 只跑一次。
  // 依赖 allTemplates: 等模板加载完再反查 template_id (否则 find 空 → InstanceSection effect 落默认)。
  const clonePrefilled = useRef(false);
  useEffect(() => {
    if (!cloneFrom) return;
    if (clonePrefilled.current) return;
    if (!templatesLoaded) return; // 等模板加载完 (即便空), 再反查, 免 spin 卡死
    if (authedPvcs === null) return; // 等授权列表, 否则无法判断源 FSx 自己有没有权限
    clonePrefilled.current = true;
    let cancelled = false;
    (async () => {
      try {
        const d = await getLlmd(cloneFrom);
        form.setFieldsValue(mapDetailToFormValues(d));
        // 一块盘对读写/只读用户是两个 pvc 名 (…-rw / …-ro), 权限不同就匹配不上 → 留空
        if (d.model_source_type === 'fsx' && d.model_pvc) {
          const mine = (authedPvcs ?? []).find((x) => x.name === d.model_pvc);
          if (mine) {
            form.setFieldValue('model_pvc', d.model_pvc);
          } else {
            const base = d.model_pvc.replace(/-(rw|ro)$/, '');
            const same = (authedPvcs ?? []).find(
              (x) => x.name.replace(/-(rw|ro)$/, '') === base,
            );
            message.warning(
              same
                ? same.access === 'ro'
                  ? t('create.messages.cloneFsxReadOnly')
                  : t('create.messages.cloneFsxReadWrite')
                : t('create.messages.cloneFsxMissing'),
              8,
            );
          }
        }
        // 资源模板反查: 用 gpu/cpu/mem 真值匹配已加载模板 → 回填 template_id
        const cpuCores = Math.round((d.cpu_request_millicores ?? 0) / 1000);
        const memGib = Math.round((d.memory_request_mib ?? 0) / 1024);
        const hit = allTemplates.find(
          (tpl) =>
            tpl.resource.gpu === d.gpu_per_pod &&
            tpl.resource.cpu_cores === cpuCores &&
            tpl.resource.mem_gib === memGib,
        );
        if (hit) form.setFieldValue('template_id', hit.template_id);
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof ApiError ? err.message : String(err);
        message.error(t('create.messages.cloneFetchFailed', { error: msg }));
      } finally {
        setCloneLoading(false);
        if (!cancelled) {
          setTimeout(
            () => document.getElementById('llmd-preview')?.scrollIntoView({ behavior: 'smooth' }),
            150,
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cloneFrom, templatesLoaded, authedPvcs]);

  const modelSourceType = Form.useWatch('model_source_type', form);
  const watchedReplicas = Form.useWatch('replicas', form);
  const watchedNodes = Form.useWatch('nodes_per_replica', form);
  const watchedGpuPerPod = Form.useWatch('gpu_per_pod', form);
  const requestedGpu = useMemo(
    () => (watchedReplicas ?? 1) * (watchedNodes ?? 2) * (watchedGpuPerPod ?? 0),
    [watchedReplicas, watchedNodes, watchedGpuPerPod],
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
      const { yaml } = await previewLlmd(wsId, buildPayload(v));
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
      const detail = await createLlmd(wsId, buildPayload(v));
      message.success(t('create.messages.created'));
      navigate(`/workspaces/${wsId}/llmd/${detail.id}`);
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
                model_source_type: 'fsx',
                launch_script: defaultLaunchScript(),
                replicas: 1,
                nodes_per_replica: 2,
                gpu_per_pod: 1,
                efa_per_pod: 0,
                gateway_image: DEFAULT_GATEWAY_IMAGE,
                sglang_image: DEFAULT_SGLANG_IMAGE,
                gateway_replicas: 1,
                gateway_extra_args: DEFAULT_GATEWAY_ARGS,
                gateway_cpu_request_millicores: 1000,
                gateway_cpu_limit_millicores: 4000,
                gateway_memory_request_mib: 2048,
                gateway_memory_limit_mib: 8192,
                expose_alb: false,   // 默认不建 ALB (省钱省子网 IP)
                label_pairs: [],
              }}
            >
              <div id="llmd-basic">
                <Typography.Title level={5}>{t('create.sections.basic')}</Typography.Title>
                <BasicSection />
              </div>
              <Divider />
              <div id="llmd-gateway">
                <Typography.Title level={5}>{t('create.sections.gateway')}</Typography.Title>
                <GatewaySection
                  allTemplates={allTemplates}
                  wsInstanceTypes={wsInstanceTypes}
                  instTypePool={instTypePool}
                  instTypeGpuSpec={instTypeGpuSpec}
                  onReloadTemplates={refreshTemplates}
                  templatesLoading={templatesLoading}
                />
              </div>
              <Divider />
              <div id="llmd-worker">
                <Typography.Title level={5}>{t('create.sections.worker')}</Typography.Title>
                <ImageSection wsId={wsId} />
                <div style={{ height: 12 }} />
                <ModelSourceSection
                  modelSourceType={modelSourceType ?? 'fsx'}
                  authedFsxMounts={authedFsxMounts}
                  authedPvcs={authedPvcs}
                  fsxMounts={fsxMounts}
                  wsS3Mounts={wsS3Mounts}
                  onReload={reloadMounts}
                  mountsLoading={mountsLoading}
                />
                <div style={{ height: 12 }} />
                <InstanceSection
                  wsInstanceTypes={wsInstanceTypes}
                  instTypePool={instTypePool}
                  instTypeGpuSpec={instTypeGpuSpec}
                  allTemplates={allTemplates}
                  remainingGpu={remainingGpu}
                  quotaTotalGpu={quotaTotalGpu}
                  requestedGpu={requestedGpu}
                  watchedReplicas={watchedReplicas}
                  watchedNodes={watchedNodes}
                  watchedGpuPerPod={watchedGpuPerPod}
                  gpuOverQuota={gpuOverQuota}
                  onReloadTemplates={refreshTemplates}
                  templatesLoading={templatesLoading}
                />
              </div>
              <Divider />
              <div id="llmd-command">
                <Typography.Title level={5}>{t('create.sections.launch')}</Typography.Title>
                <CommandSection />
              </div>
              <Divider />
              <div id="llmd-preview">
                <Typography.Title level={5}>{t('create.sections.preview')}</Typography.Title>
                <AdvancedSection previewYaml={previewYaml} onPreview={buildPreview} />
              </div>

              <Space style={{ marginTop: 24 }}>
                <Button type="primary" icon={<RocketOutlined />} loading={submitting} onClick={onSubmit}>
                  {t('common:actions.submit')}
                </Button>
                <Button onClick={() => navigate(`/workspaces/${wsId}/llmd`)}>
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
                ['gateway', 'Gateway'],
                ['worker', 'Worker'],
                ['command', t('create.sections.launch')],
                ['preview', t('create.sections.preview')],
              ].map(([key, label]) => ({
                key,
                href: `#llmd-${key}`,
                title: <span style={{ display: 'block', padding: '6px 0' }}>{label}</span>,
              }))}
            />
          </Col>
        </Row>
      </Spin>
    </ProCard>
  );
}
