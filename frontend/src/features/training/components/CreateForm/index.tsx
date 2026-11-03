import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Anchor,
  Button,
  Col,
  Divider,
  Form,
  Row,
  Space,
  Spin,
  Typography,
  message,
} from 'antd';
import { RocketOutlined } from '@ant-design/icons';
import { ProCard } from '@ant-design/pro-components';
import yaml from 'js-yaml';
import { ApiError } from '@/shared/api';
import { useAppStore } from '@/store';
import {
  createTrainingJob,
  getTrainingJob,
  previewTrainingJob,
} from '../../api/client';
import type {
  ExtraFsxMount,
  FsxMountRef,
  S3DatasetRef,
  TrainingJobCreatePayload,
  TrainingJobDetail,
} from '../../api/types';
import {
  aggregateQuota,
  getWorkspaceQuota,
  getWorkspaceQuotaUsage,
} from '@/features/quota/api';
import {
  listWorkspaceS3,
  type WorkspaceS3Mount,
} from '@/features/workspace/api';
import {
  listSharedPVCs,
  type SharedPVCInfo,
} from '@/features/devinstance/api/client';
import {
  listResourceTemplates,
  type ResourceTemplateItem,
} from '@/api/resource-templates';
import type { Pool } from '@/api/resource-pool';
import type { TopologyLabel, TopologyMode } from '../../api/types';
import BasicSection from './BasicSection';
import ImageSection from './ImageSection';
import StorageSection from './StorageSection';
import ResourceSection from './ResourceSection';
import LaunchSection, { type ScriptExampleKind } from './LaunchSection';
import PreviewSection from './PreviewSection';

const DEFAULTS = {
  image: 'pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime',
  fsx_mount_path: '/fsx',
  priority_class: 'common-priority',
};

// runPolicy 编辑框初值 (用户可改, 与后端 cr.py 默认对齐)。
// restartPolicy 是 CRD required (evalPeriodSeconds), 必带 — 否则预览/真 CR 会被补上, 编辑框对不上。
const DEFAULT_RUNPOLICY_YAML = `cleanPodPolicy: All
jobMaxRetryCount: 0
ttlSecondsAfterFinished: -1
restartPolicy:
  numRestartBeforeFullJobRestart: 3
  evalPeriodSeconds: 3600
  maxFullJobRestarts: 1
`;

interface FormValues {
  // 表单无任务名字段: 后端从 display_name 派生
  display_name: string;
  description?: string;
  image_source?: 'manual' | 'ecr';
  image: string;
  instance_type?: string;
  node_count: number;
  spares?: number;
  gpu_per_node: number;
  efa_per_node?: number;
  cpu_per_node_cores: number;
  memory_per_node_gib: number;
  fsx_pvc?: string;
  fsx_mount_path: string;
  script_inline?: string;
  env_pairs: { key: string; value: string }[];
  topology_mode?: TopologyMode;
  topology_label?: TopologyLabel;
  runpolicy_yaml?: string;
  auto_wrap?: boolean;
  template_id?: string;
  label_pairs: { key: string; value: string }[];
  // 从 Secret 注入的环境变量 (只选 key, env 名 = key 名)
  env_secret_pairs?: { secret_key?: string }[];
}

// 启动 command: 直接编写的脚本整段字符串 (后端 -lc 跑)。
function buildLaunchCommand(values: FormValues): string | string[] {
  return (values.script_inline ?? '').trim();
}

function buildPayload(
  values: FormValues,
  fsxRefs?: FsxMountRef[],
  s3Refs?: S3DatasetRef[],
): TrainingJobCreatePayload {
  const env: Record<string, string> = {};
  for (const p of values.env_pairs || []) {
    if (p?.key) env[p.key.trim()] = (p.value ?? '').trim();
  }

  const payload: TrainingJobCreatePayload = {
    // 不传 name: 后端派生, 传了会被 422 拒; 真名从创建响应的 name 字段读
    display_name: values.display_name.trim(),
    description: values.description?.trim() || undefined,
    image: (values.image ?? '').trim(),
    command: buildLaunchCommand(values),
    node_count: values.node_count,
    spares: values.spares ?? 0,
    gpu_per_node: values.gpu_per_node,
    efa_per_node: values.efa_per_node || 0,
    cpu_per_node_millicores: Math.round((values.cpu_per_node_cores ?? 0) * 1000),
    memory_per_node_mib: Math.round((values.memory_per_node_gib ?? 0) * 1024),
    env,
    priority_class: DEFAULTS.priority_class,
    instance_type: values.instance_type || undefined,
    topology_mode: values.topology_mode || 'none',
    topology_label:
      values.topology_mode && values.topology_mode !== 'none'
        ? values.topology_label || null
        : null,
    auto_wrap: values.auto_wrap ?? false,
    labels: Object.fromEntries(
      (values.label_pairs || [])
        .filter((p) => p?.key?.trim())
        .map((p) => [p.key.trim(), (p.value ?? '').trim()]),
    ),
  };

  if (fsxRefs?.length) {
    payload.fsx_mounts = fsxRefs;
  }
  if (s3Refs?.length) {
    payload.s3_datasets = s3Refs;
  }

  // 从 Secret 注入的环境变量 (只选 key, env 名 = key 名;
  // secret_ref 后端自动补本人固定 secret 名, 前端不填)。
  const envSecrets = (values.env_secret_pairs || [])
    .filter((p) => p?.secret_key)
    .map((p) => ({
      name: p.secret_key as string,
      secret_key: p.secret_key as string,
    }));
  if (envSecrets.length) {
    payload.env_secrets = envSecrets;
  }

  // runPolicy: 用户编辑的裸 YAML → run_policy_override. 解析失败 throw (调用方捕获提示)。
  const rpRaw = (values.runpolicy_yaml ?? '').trim();
  if (rpRaw && rpRaw !== DEFAULT_RUNPOLICY_YAML.trim()) {
    const parsed = yaml.load(rpRaw);
    if (parsed && typeof parsed === 'object') {
      const obj = parsed as Record<string, unknown>;
      const inner =
        Object.keys(obj).length === 1 &&
        obj.runPolicy &&
        typeof obj.runPolicy === 'object'
          ? (obj.runPolicy as Record<string, unknown>)
          : obj;
      payload.run_policy_override = inner;
    }
  }

  return payload;
}

/** 克隆名 = 原名 + '-copy', 超 29 就先截断 (并去掉截断留下的尾部 '-')。 */
function cloneDisplayName(src: string): string {
  const SUFFIX = '-copy';
  const MAX = 29;
  const naive = `${src}${SUFFIX}`;
  if (naive.length <= MAX) return naive;
  return `${src.slice(0, MAX - SUFFIX.length).replace(/-+$/, '')}${SUFFIX}`;
}

function mapDetailToFormValues(d: TrainingJobDetail, isOwner: boolean): Partial<FormValues> {
  const img = d.image || '';
  const isEcr = img.includes('dkr.ecr');

  const envPairs = Object.entries(d.env || {}).map(([key, value]) => ({
    key,
    value: String(value ?? ''),
  }));

  // runPolicy 克隆: 用户编辑过 (run_policy_override 非空) → dump 原文 YAML 回填;
  // 否则用详情的 4 个结构化字段 (cleanPodPolicy/ttl/jobMaxRetry/activeDeadline) 拼。
  let runpolicyYaml: string;
  if (d.run_policy_override && Object.keys(d.run_policy_override).length > 0) {
    runpolicyYaml = yaml.dump(d.run_policy_override);
  } else {
    // restartPolicy 后端没回存 metadata (渲 CR 时默认补), 克隆按默认补全 —
    // 与新建表单 DEFAULT_RUNPOLICY_YAML 一致, 否则克隆缺这段。
    const rp: Record<string, unknown> = {
      cleanPodPolicy: d.clean_pod_policy ?? 'All',
      jobMaxRetryCount: d.job_max_retry_count ?? 0,
      ttlSecondsAfterFinished: d.ttl_seconds_after_finished ?? -1,
      restartPolicy: {
        numRestartBeforeFullJobRestart: 3,
        evalPeriodSeconds: 3600,
        maxFullJobRestarts: 1,
      },
    };
    if (d.active_deadline_seconds != null) {
      rp.activeDeadlineSeconds = d.active_deadline_seconds;
    }
    runpolicyYaml = yaml.dump(rp);
  }

  return {
    // 任务名不在此设: 由 BasicSection 的 useWatch 从 display_name 自动派生
    // (sanitize(显示名)+本页随机后缀), 保证唯一且改显示名不重掷随机。
    display_name: cloneDisplayName(d.display_name),
    description: d.description ?? undefined,
    image_source: isEcr ? 'ecr' : 'manual',
    image: img,
    instance_type: d.instance_type || undefined,
    node_count: d.node_count,
    spares: d.spares ?? 0,
    gpu_per_node: d.gpu_per_node,
    efa_per_node: d.efa_per_node ?? 0,
    cpu_per_node_cores: (d.cpu_per_node_millicores ?? 0) / 1000,
    memory_per_node_gib: (d.memory_per_node_mib ?? 0) / 1024,
    // command 类型 string|string[] (老数据/exec 数组), 回填编辑框统一成字符串
    script_inline: Array.isArray(d.command) ? d.command.join(' ') : (d.command ?? ''),
    env_pairs: envPairs,
    label_pairs: Object.entries(d.labels || {}).map(([key, value]) => ({
      key,
      value: String(value ?? ''),
    })),
    topology_mode: (d.topology_mode as TopologyMode) || 'none',
    topology_label: (d.topology_label as TopologyLabel) ?? undefined,
    runpolicy_yaml: runpolicyYaml,
    // env_secrets 克隆: owner 克隆自己的任务 → 预填 key 省重选;
    // 他人克隆 → 清空 (key 是原作者库的, 他人库未必有; 后端 secret_ref 恒绑操作者本人, 借不到)。
    // 两者都保留 secret 区可见 (他人可加自己库的 key)。
    env_secret_pairs: (d.env_secrets || []).map((s) => ({
      secret_key: isOwner ? s.secret_key : undefined,
    })),
  };
}

export default function CreateForm() {
  const { wsId = '' } = useParams();
  const { t } = useTranslation(['training', 'common']);
  const currentUser = useAppStore((s) => s.currentUser);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const cloneFrom = searchParams.get('cloneFrom');
  const [form] = Form.useForm<FormValues>();
  const [submitting, setSubmitting] = useState(false);
  // 克隆模式: 拉源配置期间盖 loading, 加载完才可编辑 (避免用户改了又被预填覆盖)
  const [cloneLoading, setCloneLoading] = useState<boolean>(!!cloneFrom);
  const [quotaTotalGpu, setQuotaTotalGpu] = useState<number>(0);
  const [usageUsedGpu, setUsageUsedGpu] = useState<number>(-1);
  const [wsInstanceTypes, setWsInstanceTypes] = useState<string[]>([]);
  // 机型→资源池 映射 (后端 quota.resources[].pool, EC2 权威判)。分 CPU/GPU 池筛机型用。
  const [instTypePool, setInstTypePool] = useState<Record<string, Pool>>({});
  // 机型→GPU 描述 映射 (如 "4×A10G"), 供 Select label 展示。
  const [instTypeGpuSpec, setInstTypeGpuSpec] = useState<Record<string, string>>({});
  const [exampleKind, setExampleKind] = useState<ScriptExampleKind>('none');
  const [previewYamlText, setPreviewYamlText] = useState<string>('');
  const [previewLoading, setPreviewLoading] = useState(false);

  const [sharedPvcs, setSharedPvcs] = useState<SharedPVCInfo[] | null>(null);
  // 暂存克隆源的 FSx, 待授权列表到达后按权限筛 (clone effect 只跑一次)
  const [clonedFsxMounts, setClonedFsxMounts] = useState<ExtraFsxMount[] | null>(
    null,
  );
  const [fsxChecked, setFsxChecked] = useState<string[]>([]);
  const [s3Checked, setS3Checked] = useState<string[]>([]);
  const [wsS3Mounts, setWsS3Mounts] = useState<WorkspaceS3Mount[]>([]);
  const [mountsLoading, setMountsLoading] = useState(false);

  // 可挂载列表 (FSx shared-pvcs + S3) 抽成 reload: effect 首次调, 共享存储的
  // 刷新按钮也调 (在别处新授权/挂载 FSx/S3 后即时可选, 不清空已填内容)。
  const reloadMounts = useCallback(() => {
    if (!wsId) return;
    setMountsLoading(true);
    Promise.allSettled([listSharedPVCs(wsId), listWorkspaceS3(wsId)])
      .then(([pvcs, s3]) => {
        setSharedPvcs(pvcs.status === 'fulfilled' ? pvcs.value : []);
        setWsS3Mounts(s3.status === 'fulfilled' ? s3.value : []);
      })
      .finally(() => setMountsLoading(false));
  }, [wsId]);
  useEffect(() => {
    reloadMounts();
  }, [reloadMounts]);

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
            need: t(m.read_only ? 'create.access.ro' : 'create.access.rw'),
            have: t(mine.access === 'ro' ? 'create.access.ro' : 'create.access.rw'),
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

  const [allTemplates, setAllTemplates] = useState<ResourceTemplateItem[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const refreshTemplates = useCallback(() => {
    if (!wsId) return;
    // 默认模板选择交给 ResourceSection 的切池 effect (按当前池筛后选最小),
    // 避免这里选了全局最小 (可能是 CPU 模板) 与默认 GPU 池不符 → Select 显示裸 id。
    setTemplatesLoading(true);
    listResourceTemplates(wsId)
      .then((list) => setAllTemplates(list))
      .catch(() => setAllTemplates([]))
      .finally(() => setTemplatesLoading(false));
  }, [wsId]);
  useEffect(() => {
    refreshTemplates();
  }, [refreshTemplates]);

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
          // 自动选首个机型逻辑移到 ResourceSection 的切池 effect (按池筛后选首个)
        }
        if (u.status === 'fulfilled') {
          setUsageUsedGpu(u.value.totals.accelerators);
        }
      },
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId]);

  // 克隆: ?cloneFrom=<id> → 拉源任务详情 + 模板反查 → 预填整页 → 滚到预览区。
  // 全程盖 cloneLoading, 加载完才可编辑 (避免用户改了又被异步预填覆盖)。
  useEffect(() => {
    if (!cloneFrom) return;
    let cancelled = false;
    (async () => {
      try {
        const d = await getTrainingJob(cloneFrom);
        if (cancelled) return;
        // owner 克隆自己的任务才预填 secret key (他人克隆清空; 后端 secret_ref 恒绑操作者本人)
        const isOwner = !!currentUser && d.creator_user_id === currentUser.id;
        form.setFieldsValue(mapDetailToFormValues(d, isOwner));

        // 资源反查 (B 方案): gpu/cpu/mem 模板锁定, 详情无 template_id → 用真值反查
        // 当前模板列表匹配, 命中预填 template_id (UI 正常选中); 未命中提示重选。
        // 单位: 详情 cpu=millicores/mem=MiB → 模板 cpu_cores/mem_gib, 换算对齐。
        const cpuCores = (d.cpu_per_node_millicores ?? 0) / 1000;
        const memGib = (d.memory_per_node_mib ?? 0) / 1024;
        try {
          const tpls = await listResourceTemplates(wsId);
          if (cancelled) return;
          const hit = tpls.find(
            (tpl) =>
              tpl.resource.gpu === d.gpu_per_node &&
              tpl.resource.cpu_cores === cpuCores &&
              tpl.resource.mem_gib === memGib,
          );
          if (hit) {
            form.setFieldValue('template_id', hit.template_id);
            // EFA 已并入模板锁定: 克隆按命中模板的 efa 同步 (老模板 → 0),
            // 而非沿用源任务的旧 efa_per_node, 保持与锁定显示一致。
            form.setFieldValue('efa_per_node', hit.resource.efa ?? 0);
          } else {
            message.warning(t('create.messages.cloneTemplateChanged'));
          }
        } catch {
          /* 模板反查失败不阻塞克隆 */
        }

        // FSx/S3 是 state (非 form): 从详情挂载引用回填选中。
        // (注: 详情 s3 用 pvc_name, 创建用 mount_id; 不一定对应 — 用户可手选。)
        setClonedFsxMounts(d.extra_fsx_mounts ?? []);
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof ApiError ? err.message : String(err);
        message.error(t('create.messages.cloneFetchFailed', { error: msg }));
      } finally {
        if (!cancelled) {
          setCloneLoading(false);
          // 加载完滚到预览区 (= "跳到第5步")
          setTimeout(
            () =>
              document
                .getElementById('tr-preview')
                ?.scrollIntoView({ behavior: 'smooth' }),
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

  const watchedNodeCount = Form.useWatch('node_count', form);
  const watchedGpuPerNode = Form.useWatch('gpu_per_node', form);
  const watchedSpares = Form.useWatch('spares', form);
  const requestedGpu = useMemo(
    () =>
      ((watchedNodeCount ?? 1) + (watchedSpares ?? 0)) *
      (watchedGpuPerNode ?? 0),
    [watchedNodeCount, watchedSpares, watchedGpuPerNode],
  );
  const gpuOverQuota = remainingGpu !== null && requestedGpu > remainingGpu;

  const buildFsxRefs = useCallback(
    (): FsxMountRef[] =>
      (sharedPvcs || [])
        .filter((p) => fsxChecked.includes(p.name) && p.mount_path)
        .map((p) => ({ pvc_name: p.name })),
    [sharedPvcs, fsxChecked],
  );

  const buildS3Datasets = useCallback(
    (): S3DatasetRef[] => s3Checked.map((mount_id) => ({ mount_id })),
    [s3Checked],
  );

  const fetchPreview = useCallback(async () => {
    setPreviewLoading(true);
    try {
      const values = form.getFieldsValue(true) as FormValues;
      let payload: TrainingJobCreatePayload;
      try {
        payload = buildPayload(values, buildFsxRefs(), buildS3Datasets());
      } catch (e) {
        setPreviewYamlText(
          t('create.yamlComments.runPolicyParseFailed', { error: (e as Error).message }),
        );
        return;
      }
      const { yaml: text } = await previewTrainingJob(wsId, payload);
      setPreviewYamlText(text);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : (err as Error).message;
      setPreviewYamlText(t('create.yamlComments.renderFailed', { error: msg }));
    } finally {
      setPreviewLoading(false);
    }
  }, [form, wsId, buildFsxRefs, buildS3Datasets, t]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      const payload = buildPayload(values, buildFsxRefs(), buildS3Datasets());
      const detail = await createTrainingJob(wsId, payload);
      message.success(t('create.messages.submitted', { name: detail.k8s_job_name }));
      navigate(`/workspaces/${wsId}/training/${detail.id}`);
    } catch (err) {
      if (err && typeof err === 'object' && 'errorFields' in err) {
        const ef = (err as { errorFields?: Array<{ name: string[]; errors: string[] }> }).errorFields;
        const first = ef?.[0];
        const fieldName = first?.name?.join('.') ?? '?';
        const errMsg = first?.errors?.[0] ?? '';
        message.error(t('create.messages.fieldInvalid', { field: fieldName, error: errMsg }));
        return;
      }
      const msg = err instanceof ApiError ? err.message : (err as Error).message;
      message.error(t('create.messages.submitFailed', { error: msg }));
    } finally {
      setSubmitting(false);
    }
  };

  // 默认值 (原 Form initialValues); 克隆预留: 阶段二改为 { ...baseInitial, ...clonedValues }
  const baseInitial: Partial<FormValues> = {
    display_name: '',
    image_source: 'manual',
    image: DEFAULTS.image,
    script_inline: '',
    node_count: 1,
    spares: 0,
    gpu_per_node: 1,
    efa_per_node: 0,
    cpu_per_node_cores: 4,
    memory_per_node_gib: 16,
    fsx_mount_path: DEFAULTS.fsx_mount_path,
    env_pairs: [],
    label_pairs: [],
    topology_mode: 'none',
    runpolicy_yaml: DEFAULT_RUNPOLICY_YAML,
  };
  const initialValues = baseInitial;

  return (
    <ProCard bordered>
      <Spin spinning={cloneLoading} tip={t('create.loadingConfig')}>
      <Row gutter={24} wrap={false}>
        <Col flex="auto" style={{ minWidth: 0 }}>
          <Form<FormValues> form={form} layout="vertical" className="hp-create-form" initialValues={initialValues}>
            <div id="tr-basic">
              <Typography.Title level={5}>{t('create.sections.basic')}</Typography.Title>
              <BasicSection />
            </div>
            <Divider />
            <div id="tr-image">
              <Typography.Title level={5}>{t('create.sections.image')}</Typography.Title>
              <ImageSection wsId={wsId} />
            </div>
            <Divider />
            <div id="tr-storage">
              <Typography.Title level={5}>{t('create.sections.storage')}</Typography.Title>
              <StorageSection
                sharedPvcs={sharedPvcs}
                fsxChecked={fsxChecked}
                onFsxChange={setFsxChecked}
                wsS3Mounts={wsS3Mounts}
                s3Checked={s3Checked}
                onS3Change={setS3Checked}
                onReload={reloadMounts}
                mountsLoading={mountsLoading}
              />
            </div>
            <Divider />
            <div id="tr-resource">
              <Typography.Title level={5}>{t('create.sections.resource')}</Typography.Title>
              <ResourceSection
                wsId={wsId}
                wsInstanceTypes={wsInstanceTypes}
                instTypePool={instTypePool}
                instTypeGpuSpec={instTypeGpuSpec}
                allTemplates={allTemplates}
                remainingGpu={remainingGpu}
                quotaTotalGpu={quotaTotalGpu}
                requestedGpu={requestedGpu}
                watchedNodeCount={watchedNodeCount}
                watchedGpuPerNode={watchedGpuPerNode}
                gpuOverQuota={gpuOverQuota}
                onReloadTemplates={refreshTemplates}
                templatesLoading={templatesLoading}
              />
            </div>
            <Divider />
            <div id="tr-launch">
              <Typography.Title level={5}>{t('create.sections.launch')}</Typography.Title>
              <LaunchSection
                exampleKind={exampleKind}
                onPickExample={setExampleKind}
              />
            </div>
            <Divider />
            <div id="tr-preview">
              <Typography.Title level={5}>{t('create.sections.preview')}</Typography.Title>
              <PreviewSection
                previewYaml={previewYamlText}
                previewLoading={previewLoading}
                onRefreshPreview={() => void fetchPreview()}
              />
            </div>

            <Space style={{ marginTop: 24 }}>
              <Button
                type="primary"
                icon={<RocketOutlined />}
                loading={submitting}
                onClick={handleSubmit}
              >
                {t('create.submit')}
              </Button>
              <Button onClick={() => navigate(`/workspaces/${wsId}/training`)}>
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
              ['storage', t('create.sections.storage')],
              ['resource', t('create.sections.resource')],
              ['launch', t('create.sections.launch')],
              ['preview', t('create.sections.preview')],
            ].map(([key, label]) => ({
              key,
              href: `#tr-${key}`,
              // 英文标题更长, 允许换行而不是撑破 160px 锚点列
              title: (
                <span style={{ display: 'block', padding: '6px 0', whiteSpace: 'normal' }}>
                  {label}
                </span>
              ),
            }))}
          />
        </Col>
      </Row>
      </Spin>
    </ProCard>
  );
}
