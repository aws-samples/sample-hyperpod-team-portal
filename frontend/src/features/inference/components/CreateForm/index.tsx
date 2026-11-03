import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import i18n from '@/shared/i18n';
import { createInference, getInference, previewInference } from '../../api/client';
import {
  listWorkspaceFsx,
  listWorkspaceS3,
  type WorkspaceFsxMount,
  type WorkspaceS3Mount,
} from '@/features/workspace/api';
import {
  listSharedPVCs,
  type SharedPVCInfo,
} from '@/features/devinstance/api/client';
import {
  aggregateQuota,
  getWorkspaceQuota,
  getWorkspaceQuotaUsage,
} from '@/features/quota/api';
import type {
  InferenceCreatePayload,
  InferenceDetail,
  ModelSourceType,
  RoutingStrategy,
} from '../../api/types';
import {
  listResourceTemplates,
  type ResourceTemplateItem,
} from '@/api/resource-templates';
import type { Pool } from '@/api/resource-pool';
import BasicSection from './BasicSection';
import ModelSourceSection from './ModelSourceSection';
import InstanceSection from './InstanceSection';
import ImageSection from './ImageSection';
import CommandSection from './CommandSection';
import AdvancedSection from './AdvancedSection';

const DEFAULTS = {
  framework: 'sglang' as const,
  image: 'lmsysorg/sglang:latest',
  invocation_endpoint: 'v1/chat/completions',
  container_port: 8000,
  instance_type: '',  // 不写死: useEffect 从 ws ComputeQuota 拉首个机型填充
  gpu_per_replica: 1,
  // UI 单位 = 核 / GiB; 提交转 millicores / MiB (1 核 = 1000m, 1 GiB = 1024 MiB)
  // 推理 req=lim (不区分); 进页面默认选最小模板会覆盖这些初值。
  cpu_request_cores: 8,
  cpu_limit_cores: 8,
  memory_request_gib: 32,
  memory_limit_gib: 32,
  replicas: 1,
  routing_strategy: 'roundrobin' as RoutingStrategy,
  // Kueue 优先级 UI 已删, 统一默认 80 (与训练一致)
  priority_value: 80,
};

// 默认启动脚本. SGLang 单脚本启动. --model-path 填模型绝对路径 (FSx 如 /fsx/checkpoint;
// S3 prefetch 写 /opt/ml/model). exec 接管主进程, 后端渲 /bin/sh -c.
// 代码本体两种语言逐字节一致, 只有尖括号占位符里的路径说明随语言。
// 函数(非模块级常量): 调用时才取翻译, 避免模块加载期求值。
function defaultLaunchScript(): string {
  const modelPath = i18n.t('create.launch.scriptModelPathPlaceholder', { ns: 'inference' });
  return `exec python3 -m sglang.launch_server --model-path </fsx/checkpoint/${modelPath}> --host 0.0.0.0 --port 8000 --enable-metrics --context-length 8192 --trust-remote-code`;
}

// SGLang 暂不支持 Smart Routing, 路由策略 UI 已移除, 固定 roundrobin 提交。

// 机型不再写死: 从 workspace ComputeQuota 已分配的 instance_type 动态来 (见 wsInstanceTypes)。
// 后端 create/preview 也校验机型 ∈ ws 配额 (API 公网防越权)。

interface FormValues {
  // 表单无任务名字段: 后端从 display_name 派生
  display_name: string;
  description?: string;
  model_source_type: ModelSourceType;
  // FSx 单选挂载源 (mount_id); 提交时拆 filesystem_id/mountName, modelLocation 空挂整层,
  // 模型路径在启动脚本写。
  fsx_mount_id?: string;
  // S3 单选挂载源 (mount_id); bucket/region 提交时从选中 mount 带出
  s3_mount_id?: string;
  s3_model_location?: string;
  hf_model_id?: string;
  // model_name 已去 UI 输入: 提交时用 name 派生 (见 buildPayload)
  instance_type: string;
  gpu_per_replica: number;
  // UI 输入单位 = 核 / GiB; 提交 payload 转 millicores / MiB
  cpu_request_cores: number;
  cpu_limit_cores: number;
  memory_request_gib: number;
  memory_limit_gib: number;
  replicas: number;
  // SGLang 单脚本启动 (合并 command+args). 提交时后端渲 /bin/sh -c + args=[脚本]。
  launch_script?: string;
  // 镜像来源 2 选 1 (照训练): 'manual'=基础镜像手填完整名(默认) / 'ecr'=自定义 ECR
  image_source?: 'manual' | 'ecr';
  image: string;
  invocation_endpoint: string;
  // 容器端口 (Pod modelInvocationPort + metrics 端口), 资源页可设, 默认 8000
  container_port: number;
  // routing_strategy UI 已删 (SGLang 暂不支持), 固定 roundrobin 提交 (后端字段保留)
  routing_strategy: RoutingStrategy;
  metrics_enabled: boolean;
  public_endpoint: boolean;
  label_pairs: { key: string; value: string }[];
  // priority_value UI 已删 (统一默认 80), 用 DEFAULTS.priority_value 提交
  // template_id: 仅 UI 选模板用 (触发资源填充), 不进提交 payload
  template_id?: string;
}

// 开发机绝对路径 (如 /fsx/team-a-data/models/qwen3) → operator FSx 模型源字段。
// 按授权 FSx 的 mount_path 前缀匹配, 拆出 operator 要的 4 个字段:
//   filesystem_id / mount_name (lustre名拼subdir, 锁 team 层) / dns_name / model_location.
// model_location = 绝对路径去掉 mount_path 前缀的相对部分 (operator 挂 mountName 到
// /opt/ml/model, modelLocation 相对该挂载点)。
// 匹配不上 (路径不在任何授权 FSx 下) 抛错, 引导用户用授权目录。
// 单选 FSx 挂载源 → operator 要的 fsx 字段。modelLocation 留空 → operator 挂整层到
// /opt/ml/model, 模型相对路径在启动脚本里写。
function buildFsxFromMount(
  mountId: string,
  mounts: WorkspaceFsxMount[],
): {
  filesystem_id: string;
  model_location: string;
  mount_name: string | null;
  dns_name: string | null;
} {
  const m = mounts.find((x) => x.mount_id === mountId);
  if (!m) {
    throw new Error(i18n.t('create.messages.fsxNotAuthorized', { ns: 'inference', id: mountId }));
  }
  return {
    filesystem_id: m.filesystem_id,
    // mountName = operator/PV 挂载名 (lustre名/subdir), 锁 team 层
    mount_name: m.full_mount_name || m.mount_name || null,
    model_location: '', // 空 → 挂整层, 脚本写 --model-path
    dns_name: m.dns_name || null,
  };
}

function buildPayload(
  v: FormValues,
  fsxMounts: WorkspaceFsxMount[],
  s3Mounts: WorkspaceS3Mount[],
): InferenceCreatePayload {
  const fsx =
    v.model_source_type === 'fsx' && v.fsx_mount_id
      ? buildFsxFromMount(v.fsx_mount_id, fsxMounts)
      : null;
  // 挂载点 = 选中 FSx 的 mount_path (对齐训练/开发机); 非 FSx 回退 operator 默认
  const fsxMountPath = fsxMounts.find((m) => m.mount_id === v.fsx_mount_id)?.mount_path;
  // S3: 选中挂载源带出 bucket/region; 用户填模型相对路径
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
  const huggingface =
    v.model_source_type === 'huggingface' && v.hf_model_id
      ? { model_id: v.hf_model_id, prefetch_enabled: true }
      : null;
  // 单脚本启动: 整段交后端, 渲 command=["/bin/sh","-c"] + args=[脚本] (空则后端默认)
  const launchScript = (v.launch_script || '').trim();
  // 镜像来源二选一: ecr → 拼 repo:tag; manual(默认) → 基础镜像完整名
  const finalImage = (v.image ?? '').trim();
  return {
    // 不传 name: 后端派生 (model_name 也随之派生), 传了会被 422 拒;
    // 真名从创建响应的 name 字段读
    display_name: v.display_name,
    description: v.description || null,
    framework: 'sglang',
    model_source_type: v.model_source_type,
    fsx,
    s3,
    huggingface,
    // 不传 model_name: 后端用派生出的任务名当 modelName
    model_mount_path: fsxMountPath || '/opt/ml/model',
    instance_type: v.instance_type,
    gpu_per_replica: v.gpu_per_replica,
    // UI 单位 → 后端 schema (1 核 = 1000 millicores, 1 GiB = 1024 MiB)
    // 推理 req=lim (UI 只显示单值): limit 直接取 request 值, 不读 limit 字段。
    cpu_request_millicores: Math.round((v.cpu_request_cores ?? 0) * 1000),
    cpu_limit_millicores: Math.round((v.cpu_request_cores ?? 0) * 1000),
    memory_request_mib: Math.round((v.memory_request_gib ?? 0) * 1024),
    memory_limit_mib: Math.round((v.memory_request_gib ?? 0) * 1024),
    replicas: v.replicas,
    // 走单脚本 launch_script (合并 command+args); 旧两框字段传空 (后端兼容)
    sglang_extra_args: [],
    sglang_command: [],
    sglang_args: [],
    launch_script: launchScript || null,
    image: finalImage,
    invocation_endpoint: v.invocation_endpoint,
    container_port: v.container_port ?? DEFAULTS.container_port,
    // SGLang 暂不支持 Smart Routing, 固定 roundrobin (UI 已删路由选择)
    routing_strategy: 'roundrobin',
    l2_kv_cache: {
      enabled: false,
      backend: 'redis',
      redis_endpoint: '',
    },
    metrics_enabled: v.metrics_enabled,
    public_endpoint: v.public_endpoint,
    labels: Object.fromEntries(
      (v.label_pairs || [])
        .filter((p) => p?.key?.trim())
        .map((p) => [p.key.trim(), (p.value ?? '').trim()]),
    ),
    priority_value: DEFAULTS.priority_value,
    env: {},
  };
}

function buildYamlPreview(p: InferenceCreatePayload): string {
  const spec: Record<string, unknown> = {
    modelName: `${p.display_name}-xxxxxxxxxx`,
    endpointName: `${p.display_name}-xxxxxxxxxx`,
    instanceType: p.instance_type,
    invocationEndpoint: p.invocation_endpoint,
    replicas: p.replicas,
    modelSourceConfig:
      p.model_source_type === 'fsx' && p.fsx
        ? {
            modelSourceType: 'fsx',
            fsxStorage: { fileSystemId: p.fsx.filesystem_id },
            modelLocation: p.fsx.model_location,
          }
        : p.model_source_type === 's3' && p.s3
        ? {
            modelSourceType: 's3',
            prefetchEnabled: true,
            s3Storage: { bucketName: p.s3.bucket_name, region: p.s3.region },
            modelLocation: p.s3.model_location,
          }
        : p.huggingface
        ? {
            modelSourceType: 'huggingface',
            prefetchEnabled: true,
            huggingFaceModel: { modelId: p.huggingface.model_id },
          }
        : {},
    metrics: p.metrics_enabled
      ? { enabled: true, modelMetrics: { port: p.container_port, path: '/metrics' } }
      : undefined,
    worker: {
      image: p.image,
      // 单脚本 launch_script 非空 → /bin/sh -c + [脚本] (同后端 cr.py); 空则默认拼装
      command: p.launch_script
        ? ['/bin/sh', '-c']
        : ['python3', '-m', 'sglang.launch_server'],
      args: p.launch_script
        ? [p.launch_script]
        : [
            '--model-path', '/opt/ml/model',
            '--host', '0.0.0.0',
            '--port', String(p.container_port),
            '--enable-metrics',
            '--context-length', '8192',
            '--trust-remote-code',
            ...p.sglang_extra_args,
          ],
      modelInvocationPort: { containerPort: p.container_port, name: 'http' },
      modelVolumeMount: { name: 'model-weights', mountPath: '/opt/ml/model' },
      resources: {
        requests: {
          'nvidia.com/gpu': String(p.gpu_per_replica),
          cpu: `${p.cpu_request_millicores}m`,
          memory: `${p.memory_request_mib}Mi`,
        },
        limits: {
          'nvidia.com/gpu': String(p.gpu_per_replica),
          cpu: `${p.cpu_limit_millicores}m`,
          memory: `${p.memory_limit_mib}Mi`,
        },
      },
    },
  };
  if (p.routing_strategy !== 'roundrobin') spec.routingStrategy = p.routing_strategy;
  return yaml.dump(
    {
      apiVersion: 'inference.sagemaker.aws.amazon.com/v1',
      kind: 'InferenceEndpointConfig',
      metadata: {
        name: `${p.display_name}-xxxxxxxxxx`,
        namespace: 'hyperpod-ns-<workspace>',
        labels: {
          'platform.hyperpod.io/inference-id': '<auto>',
          'platform.hyperpod.io/workspace-id': '<auto>',
          'platform.hyperpod.io/creator-id': '<auto>',
          'platform.hyperpod.io/framework': 'sglang',
          'kueue.x-k8s.io/queue-name': 'hyperpod-ns-<workspace>-localqueue',
          'kueue.x-k8s.io/priority-class': 'common-priority',
        },
      },
      spec,
    },
    { lineWidth: 100 },
  );
}

/** 克隆名 = 原名 + '-copy', 超 29 就先截断 (并去掉截断留下的尾部 '-')。 */
function cloneDisplayName(src: string): string {
  const SUFFIX = '-copy';
  const MAX = 29;
  const naive = `${src}${SUFFIX}`;
  if (naive.length <= MAX) return naive;
  return `${src.slice(0, MAX - SUFFIX.length).replace(/-+$/, '')}${SUFFIX}`;
}

// 克隆: InferenceDetail → 表单值 (照训练 mapDetailToFormValues)。
// FSx 绝对路径反推: detail.fsx 只有 filesystem_id + model_location, 无 mount_path。
// 须按 filesystem_id 在授权 FSx 里找 mount_path 拼回 abs (= mount_path/model_location)。
// 匹配不到 → 留空 + 让用户重填 (clone effect 内处理, 此处只拆 detail 自带字段)。
function mapDetailToFormValues(d: InferenceDetail): Partial<FormValues> {
  const img = d.image || '';
  const isEcr = img.includes('dkr.ecr');

  return {
    display_name: cloneDisplayName(d.display_name),
    description: d.description ?? undefined,
    model_source_type: d.model_source_type as ModelSourceType,
    // fsx_mount_id / s3_mount_id 在 clone effect 内按 filesystem_id/bucket 反查授权挂载源回填
    s3_model_location: d.s3?.model_location,
    hf_model_id: d.huggingface?.model_id,
    instance_type: d.instance_type,
    gpu_per_replica: d.gpu_per_replica,
    cpu_request_cores: (d.cpu_request_millicores ?? 0) / 1000,
    cpu_limit_cores: (d.cpu_limit_millicores ?? 0) / 1000,
    memory_request_gib: (d.memory_request_mib ?? 0) / 1024,
    memory_limit_gib: (d.memory_limit_mib ?? 0) / 1024,
    replicas: d.replicas,
    // 启动脚本: 老数据可能没存 launch_script → 回退 DEFAULTS (含完整 SGLang 命令)。
    launch_script: d.launch_script || defaultLaunchScript(),
    image_source: isEcr ? 'ecr' : 'manual',
    image: img,
    invocation_endpoint: d.invocation_endpoint || DEFAULTS.invocation_endpoint,
    container_port: d.container_port ?? DEFAULTS.container_port,
    metrics_enabled: d.metrics_enabled ?? true,
    public_endpoint: d.public_endpoint ?? false,
    label_pairs: Object.entries(d.labels || {}).map(([key, value]) => ({
      key,
      value: String(value ?? ''),
    })),
  };
}

export default function CreateForm() {
  const { t } = useTranslation(['inference', 'common']);
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const cloneFrom = searchParams.get('cloneFrom');
  const [form] = Form.useForm<FormValues>();
  const [cloneLoading, setCloneLoading] = useState<boolean>(!!cloneFrom);
  const [submitting, setSubmitting] = useState(false);
  const [previewYaml, setPreviewYaml] = useState('');
  // 模型来源 FSx: 该 user 授权的 FSx (shared-pvcs 过滤) ∩ ws fsx mount (拿 fs-id/full_mount_name/dns).
  const [fsxMounts, setFsxMounts] = useState<WorkspaceFsxMount[] | null>(null);
  const [authedPvcs, setAuthedPvcs] = useState<SharedPVCInfo[] | null>(null);
  // workspace 已挂的 S3 (模型源选 S3 时单选, bucket/region 自动带出)
  const [wsS3Mounts, setWsS3Mounts] = useState<WorkspaceS3Mount[] | null>(null);
  // 机型来自 workspace ComputeQuota 已分配的 instance_type (不写死, 后端也校验)
  const [wsInstanceTypes, setWsInstanceTypes] = useState<string[]>([]);
  // 机型→资源池 映射 (后端 quota.resources[].pool, EC2 权威判)。分 CPU/GPU 池筛机型用。
  const [instTypePool, setInstTypePool] = useState<Record<string, Pool>>({});
  // 机型→GPU 描述 映射 (如 "4×A10G"), 供 Select label 展示。
  const [instTypeGpuSpec, setInstTypeGpuSpec] = useState<Record<string, string>>({});
  // GPU 配额余量提示 (照训练 ResourceSection): 配额总卡 - 已用 = 余量。
  const [quotaTotalGpu, setQuotaTotalGpu] = useState<number>(0);
  const [usageUsedGpu, setUsageUsedGpu] = useState<number>(-1); // -1 = 用量采集中
  useEffect(() => {
    if (!wsId) return;
    let cancelled = false;
    Promise.allSettled([
      getWorkspaceQuota(wsId),
      getWorkspaceQuotaUsage(wsId),
    ]).then(([q, u]) => {
      if (cancelled) return;
      if (q.status === 'fulfilled') {
        setQuotaTotalGpu(aggregateQuota(q.value.resources).totalAccelerators);
        const types = Array.from(
          new Set(
            (q.value.resources || []).map((r) => r.instanceType).filter(Boolean),
          ),
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
        // 自动选首个机型逻辑移到 InstanceSection 的切池 effect (按池筛后选首个)
      } else {
        setWsInstanceTypes([]);
      }
      if (u.status === 'fulfilled') {
        setUsageUsedGpu(u.value.totals.accelerators);
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId]);
  // 资源模板库 · DDB (统一一套, 仅 admin 管, 用户只能选)。
  const [allTemplates, setAllTemplates] = useState<ResourceTemplateItem[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  // 抽成 useCallback: effect 首次调, 资源模板右侧刷新按钮也调 (admin 新建模板后即时可选)。
  const refreshTemplates = useCallback(() => {
    if (!wsId) return;
    // 默认模板选择交给 InstanceSection 的切池 effect (按当前池筛后选最小),
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

  // 挂载源刷新: 授权 FSx (shared-pvcs) + ws fsx mount + ws S3。
  // 抽成 useCallback 供模型源 FSx/S3 右侧刷新按钮调用; 与首次加载 effect 复用。
  // 注意不加 `=== null` 守卫: 刷新按钮就是要强制重发 (在别处新挂载 FSx/S3 后即时可选)。
  const [mountsLoading, setMountsLoading] = useState(false);
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
  // 单页进入时拉一次 (依赖 reloadMounts, 只随 wsId 变;
  // 慢请求 fsx ~19s 期间的重渲染不会重发, 因 reloadMounts 引用不变)。
  useEffect(() => {
    reloadMounts();
  }, [reloadMounts]);

  // 授权的 FSx 列表 = ws fsx mount 里, pvc 在 shared-pvcs 授权范围内的.
  // 每项携带 operator 要的 filesystem_id / full_mount_name (mountName) / dns_name.
  // 附 access(ro/rw) + isPrimary: 关联匹配的 SharedPVCInfo, 供下拉标"主/读写"标识
  // (对齐训练 StorageSection)。pvc_name_rw 命中 → rw, pvc_name_ro 命中 → ro。
  const authedFsxMounts = useMemo(() => {
    if (!fsxMounts || !authedPvcs) return [];
    const byName = new Map(authedPvcs.map((p) => [p.name, p]));
    const allowed = new Set(
      authedPvcs.flatMap((p) => [p.name]).filter(Boolean) as string[],
    );
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

  // 克隆: ?cloneFrom=<id> → 拉源推理详情 → 预填整页 → 资源 B 方案反查 → FSx 路径反推。
  // cloneLoading 期间盖整页, 防异步预填覆盖用户输入 (照训练)。
  // 依赖 fsxMounts/templates 就绪后才反查 (FSx 路径反推 + 模板匹配需要它们)。
  // ★只跑一次 guard: effect 依赖 fsxMounts, 但 fsxMounts 引用变化 (StrictMode/重渲染)
  //   会让 effect 重跑 → 重新 setFieldsValue 覆盖用户已填值 + scrollIntoView 跳到底
  //   (用户实测: 克隆页每几秒跳底 + 任务名被重置)。克隆预填本就该一次性, 加 ref 闸。
  const clonePrefilled = useRef(false);
  useEffect(() => {
    if (!cloneFrom) return;
    if (fsxMounts === null) return; // 等 FSx 加载完再反推路径
    if (authedPvcs === null) return; // 等授权列表到, 否则 authedFsxMounts 恒空 → 误判无权
    if (!allTemplates.length) return; // 等模板加载完再反查 template_id
    if (clonePrefilled.current) return; // 已成功预填过, 不再覆盖用户输入
    let cancelled = false;
    (async () => {
      try {
        const d = await getInference(cloneFrom);
        if (cancelled) return;
        form.setFieldsValue(mapDetailToFormValues(d));

        // FSx 单选: 按 filesystem_id 反查授权 FSx 的 mount_id 回填下拉。
        // 必须用 authedFsxMounts (已按本人权限筛): fsxMounts 是 ws 全量, 无权也查得到
        if (d.model_source_type === 'fsx' && d.fsx) {
          const m = authedFsxMounts.find(
            (x) => x.filesystem_id === d.fsx?.filesystem_id,
          );
          if (m) {
            form.setFieldValue('fsx_mount_id', m.mount_id);
          } else {
            message.warning(t('create.messages.cloneFsxMissing'));
          }
        }

        // S3 单选: 按 bucket_name 反查 workspace S3 挂载源的 mount_id 回填。
        if (d.model_source_type === 's3' && d.s3) {
          const sm = (wsS3Mounts ?? []).find(
            (x) => x.bucket_name === d.s3?.bucket_name,
          );
          if (sm) {
            form.setFieldValue('s3_mount_id', sm.mount_id);
          } else {
            message.warning(t('create.messages.cloneS3Missing'));
          }
        }

        // 资源 B 方案反查: gpu/cpu/mem 模板锁定, 详情无 template_id → 用真值反查。
        // 复用已加载的 allTemplates (组件挂载即拉), 不再单独 await 一次网络。
        const cpuCores = (d.cpu_request_millicores ?? 0) / 1000;
        const memGib = (d.memory_request_mib ?? 0) / 1024;
        const hit = allTemplates.find(
          (tpl) =>
            tpl.resource.gpu === d.gpu_per_replica &&
            tpl.resource.cpu_cores === cpuCores &&
            tpl.resource.mem_gib === memGib,
        );
        if (hit) {
          form.setFieldValue('template_id', hit.template_id);
        } else if (allTemplates.length) {
          message.warning(t('create.messages.cloneTemplateChanged'));
        }
        clonePrefilled.current = true; // 完整预填成功才标记, 之后重跑被挡防覆盖用户输入
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof ApiError ? err.message : String(err);
        message.error(t('create.messages.cloneFetchFailed', { error: msg }));
      } finally {
        // 无条件解锁: StrictMode 下 effect 卸载重挂 (cancelled=true) 且 clonePrefilled
        // ref 跨重挂保留 → 重挂那次被 ref 挡住不进 async, 首次这次又被 cancelled 挡住不解锁,
        // 两头都不置 false → 永久卡 loading (getInference 越慢越易触发)。React18 对已卸载
        // 组件 setState 是静默 no-op, 故这里直接置 false 无害。scrollIntoView 仅未取消时做。
        setCloneLoading(false);
        if (!cancelled) {
          setTimeout(
            () =>
              document
                .getElementById('inf-advanced')
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
  }, [cloneFrom, fsxMounts, authedPvcs, authedFsxMounts, allTemplates]);

  const initial: Partial<FormValues> = {
    model_source_type: 'fsx',
    instance_type: DEFAULTS.instance_type,
    gpu_per_replica: DEFAULTS.gpu_per_replica,
    cpu_request_cores: DEFAULTS.cpu_request_cores,
    cpu_limit_cores: DEFAULTS.cpu_limit_cores,
    memory_request_gib: DEFAULTS.memory_request_gib,
    memory_limit_gib: DEFAULTS.memory_limit_gib,
    replicas: DEFAULTS.replicas,
    container_port: DEFAULTS.container_port,
    launch_script: defaultLaunchScript(),
    image_source: 'manual',
    image: DEFAULTS.image,
    invocation_endpoint: DEFAULTS.invocation_endpoint,
    routing_strategy: DEFAULTS.routing_strategy,
    metrics_enabled: true,
    public_endpoint: false,
    label_pairs: [],
  };

  // 真渲染: 调后端 preview 端点 (与 create 共用渲染 → 预览即真相, 跟训练一致)。
  // 后端不可达 / 报错时回退本地 buildYamlPreview (仅近似)。
  const buildPreview = async () => {
    // 先校验必填 (显示名/任务名等): 缺了直接提示, 不发注定 422 的预览请求,
    // 避免回退本地近似 YAML (含 undefined / <workspace> 占位符) 误导用户。
    let v: FormValues;
    try {
      v = await form.validateFields();
    } catch {
      setPreviewYaml(t('create.messages.fillRequiredYaml'));
      message.warning(t('create.messages.fillRequiredWarn'));
      return;
    }
    let payload: InferenceCreatePayload;
    try {
      payload = buildPayload(v, authedFsxMounts, wsS3Mounts ?? []);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setPreviewYaml(`# preview build failed: ${msg}`);
      return;
    }
    setPreviewYaml(t('create.messages.rendering'));
    try {
      const { yaml: text } = await previewInference(wsId, payload);
      setPreviewYaml(text);
    } catch (err) {
      const msg = err instanceof ApiError ? `${err.status} ${err.message}` : String(err);
      // 后端失败回退本地近似 (附错误说明)
      setPreviewYaml(
        `${t('create.messages.renderFailed', { error: msg })}\n` +
          buildYamlPreview(payload),
      );
    }
  };

  const onSubmit = async () => {
    try {
      const v = await form.validateFields();
      setSubmitting(true);
      const payload = buildPayload(v, authedFsxMounts, wsS3Mounts ?? []);
      const detail = await createInference(wsId, payload);
      message.success(t('create.messages.created'));
      navigate(`/workspaces/${wsId}/inference/${detail.id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        message.error(t('create.messages.createFailed', { error: err.message }));
      } else if (err instanceof Error) {
        message.error(t('create.messages.createFailed', { error: err.message }));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const modelSourceType = Form.useWatch('model_source_type', form);
  const watchedName = Form.useWatch('name', form);

  // GPU 余量提示 (照训练): 推理需 GPU = 副本数 × 每副本 GPU。
  const watchedReplicas = Form.useWatch('replicas', form);
  const watchedGpuPerReplica = Form.useWatch('gpu_per_replica', form);
  const requestedGpu = useMemo(
    () => (watchedReplicas ?? 1) * (watchedGpuPerReplica ?? 0),
    [watchedReplicas, watchedGpuPerReplica],
  );
  const remainingGpu = useMemo(() => {
    if (usageUsedGpu < 0) return null;
    return Math.max(0, quotaTotalGpu - usageUsedGpu);
  }, [quotaTotalGpu, usageUsedGpu]);
  const gpuOverQuota = remainingGpu !== null && requestedGpu > remainingGpu;

  return (
    <ProCard bordered>
      <Spin spinning={cloneLoading} tip={t('create.loadingConfig')}>
      <Row gutter={24} wrap={false}>
        <Col flex="auto" style={{ minWidth: 0 }}>
          <Form form={form} layout="vertical" className="hp-create-form" initialValues={initial}>
            <div id="inf-basic">
              <Typography.Title level={5}>{t('create.sections.basic')}</Typography.Title>
              <BasicSection />
            </div>
            <Divider />
            <div id="inf-image">
              <Typography.Title level={5}>{t('create.sections.image')}</Typography.Title>
              <ImageSection wsId={wsId} />
            </div>
            <Divider />
            <div id="inf-model">
              <Typography.Title level={5}>{t('create.sections.model')}</Typography.Title>
              <ModelSourceSection
                modelSourceType={modelSourceType ?? 'fsx'}
                authedFsxMounts={authedFsxMounts}
                authedPvcs={authedPvcs}
                fsxMounts={fsxMounts}
                wsS3Mounts={wsS3Mounts}
                onReload={reloadMounts}
                mountsLoading={mountsLoading}
              />
            </div>
            <Divider />
            <div id="inf-instance">
              <Typography.Title level={5}>{t('create.sections.resource')}</Typography.Title>
              <InstanceSection
                wsInstanceTypes={wsInstanceTypes}
                instTypePool={instTypePool}
                instTypeGpuSpec={instTypeGpuSpec}
                allTemplates={allTemplates}
                remainingGpu={remainingGpu}
                quotaTotalGpu={quotaTotalGpu}
                requestedGpu={requestedGpu}
                watchedReplicas={watchedReplicas}
                watchedGpuPerReplica={watchedGpuPerReplica}
                gpuOverQuota={gpuOverQuota}
                onReloadTemplates={refreshTemplates}
                templatesLoading={templatesLoading}
              />
            </div>
            <Divider />
            <div id="inf-command">
              <Typography.Title level={5}>{t('create.sections.launch')}</Typography.Title>
              <CommandSection />
            </div>
            <Divider />
            <div id="inf-advanced">
              <Typography.Title level={5}>{t('create.sections.preview')}</Typography.Title>
              <AdvancedSection
                wsId={wsId}
                previewYaml={previewYaml}
                currentName={watchedName || ''}
                onPreview={buildPreview}
              />
            </div>

            <Space style={{ marginTop: 24 }}>
              <Button
                type="primary"
                icon={<RocketOutlined />}
                loading={submitting}
                onClick={onSubmit}
              >
                {t('common:actions.submit')}
              </Button>
              <Button onClick={() => navigate(`/workspaces/${wsId}/inference`)}>
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
              ['advanced', t('create.sections.preview')],
            ].map(([key, label]) => ({
              key,
              href: `#inf-${key}`,
              // 包一层撑开每项垂直间距 (AntD Anchor 默认间距偏小)
              title: (
                <span style={{ display: 'block', padding: '6px 0' }}>
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
