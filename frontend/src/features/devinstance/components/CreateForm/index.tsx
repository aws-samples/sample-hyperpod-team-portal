import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  Anchor,
  App,
  Button,
  Col,
  Divider,
  Form,
  Row,
  Space,
  Spin,
  Tooltip,
  Typography,
} from 'antd';
import { QuestionCircleOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { ProCard } from '@ant-design/pro-components';
import {
  createDevInstance,
  getDevInstance,
  listSharedPVCs,
  listTemplates,
} from '../../api/client';
import type {
  DevInstanceCreatePayload,
  DevInstanceDetail,
  TemplateInfo,
} from '../../api/types';
import { listWorkspaceS3 } from '@/features/workspace/api';
import { listResourceTemplates } from '@/api/resource-templates';
import { ApiError } from '@/shared/api';
import SharedStoragePicker, {
  type StorageItem,
} from '@/shared/ui/SharedStoragePicker';
import BasicSection from './BasicSection';
import TemplateSection from './TemplateSection';
import ImageSection from './ImageSection';
import ResourceSection from './ResourceSection';
import EnvSection, { type EnvRow } from './EnvSection';

// ws 已挂载项 (合并 fsx+s3, 给 SharedStoragePicker adapt 用)。
interface UnifiedWsMount {
  kind: 'fsx' | 's3';
  mount_path: string;
  pvc_name: string;
  access?: 'ro' | 'rw';
  isPrimary?: boolean;
  prefix?: string | null;
}

/**
 * 克隆: DevInstanceDetail → 创建表单 form values。
 * - display_name 加 -copy (用户可改); name 留空 → 后端 make_dns_name 加随机后缀保唯一,
 *   故克隆无需处理重名 (与训练/推理克隆同理, 但开发机更省心)。
 * - image 原样回填 (含 BYOI 自定义 ECR URI); cpu/mem millicores·MiB → 核·GiB。
 * - env / volume_mounts 在调用处另行回填 (envRows / 选中挂载是 state, 非 form)。
 */
function mapDetailToFormValues(d: DevInstanceDetail): Record<string, unknown> {
  return {
    // 名称回填源名 + -copy (截断 63 符合 DNS label)。开发机 DDB 名允许重复、
    // k8s 名后端加随机后缀保唯一, 故不怕撞名。
    name: `${d.name}-copy`.slice(0, 63),
    display_name: `${d.display_name}-copy`,
    description: d.description ?? undefined,
    template_name: d.template_name,
    image: d.image,
    // ⚠️ 不回填 cpu/mem/gpu 规格: 规格是"选 pool + 模板"后由 ResourceSection 自动
    // 锁定的派生值, 非独立字段。克隆搬源机规格会造成"模板已切CPU、规格仍是源机GPU值"
    // 的不一致 (切池重置 effect 因 template 已匹配新池而误判无需重置)。只回填 pool +
    // template, 规格交给 ResourceSection 按当前选择重新算 —— 用户改 pool/模板规格即跟随。
    storage_size_gib: d.storage_size_gib,
    pool: d.pool || undefined,
  };
}

/**
 * 单页长表单 for creating a dev instance.
 *
 * Owns all orchestration state (templates list, env rows, volume selection).
 * Each section is a pure child component under `./Step{N}*.tsx`, rendered in
 * one scrollable page with a right-side Anchor nav. wsId comes from the route;
 * on success navigate back to the dev-instance list.
 */
export default function CreateForm() {
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation(['devinstance', 'common']);
  const [searchParams] = useSearchParams();
  const cloneFrom = searchParams.get('cloneFrom');
  const { message } = App.useApp();
  const [form] = Form.useForm();
  // 克隆模式: 拉源开发机配置期间盖 loading, 加载完才可编辑 (避免用户改了又被预填覆盖)
  const [cloneLoading, setCloneLoading] = useState<boolean>(!!cloneFrom);
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [loadingTpl, setLoadingTpl] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [envRows, setEnvRows] = useState<EnvRow[]>([]);
  const [mounts, setMounts] = useState<UnifiedWsMount[]>([]);
  const [loadingMounts, setLoadingMounts] = useState(false);
  // FSx / S3 选中态分开 (mount_path 当键, ws 内唯一)。提交时合并回 volume_mounts。
  const [fsxSelectedPaths, setFsxSelectedPaths] = useState<string[]>([]);
  const [s3SelectedPaths, setS3SelectedPaths] = useState<string[]>([]);
  // 克隆预填后, 让"切模板"effect 跳过一次 image/storage 重置 (否则会把克隆的
  // 自定义镜像/存储覆盖成模板 default)。用户之后手动切模板不受影响。
  const justClonedRef = useRef(false);

  const selectedTemplateName = Form.useWatch('template_name', form);
  const selectedTemplate = useMemo<TemplateInfo | undefined>(
    () => templates.find((tpl) => tpl.name === selectedTemplateName),
    [templates, selectedTemplateName],
  );

  // 可挂载列表 (FSx shared-pvcs + S3) 抽成 reload: 大 effect 首次调, 共享存储的
  // 刷新按钮也调 (在别处新授权/挂载 FSx/S3 后即时可选, 不清空已填内容)。
  const reloadMounts = useCallback(() => {
    if (!wsId) return;
    setLoadingMounts(true);
    Promise.all([listSharedPVCs(wsId), listWorkspaceS3(wsId)])
      .then(([fsx, s3]) => {
        const merged: UnifiedWsMount[] = [
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
            prefix: m.prefix,
          })),
        ];
        setMounts(merged);
      })
      .catch((err) => {
        message.error(
          err instanceof ApiError
            ? err.message
            : t('create.messages.loadMountsFailed'),
        );
        setMounts([]);
      })
      .finally(() => setLoadingMounts(false));
  }, [wsId, message, t]);

  useEffect(() => {
    setLoadingTpl(true);
    listTemplates()
      .then((rows) => {
        setTemplates(rows);
        const first = rows[0];
        // 克隆模式: 不用第一个模板的默认值预填 (克隆 effect 会用源配置填), 只存列表。
        if (first && !cloneFrom) {
          form.setFieldsValue({
            template_name: first.name,
            image: first.default_image,
            // UI 单位 = 核 / GiB; 提交时换算回 millicores / MiB
            cpu_cores: first.default_cpu_millicores / 1000,
            // HyperPod ValidatingAdmissionPolicy 硬拦 memory < 8Gi;
            // 和 template 的 default_memory_mib 取 max, 避免被策略拦
            mem_gib: Math.max(first.default_memory_mib, 8192) / 1024,
            // 存储默认跟随模板 default_storage_size_gib (与 cpu/mem/image 同源),
            // 不再前端硬编码 —— 默认值由 WorkspaceTemplate.primaryStorage 权威管控
            // (当前 default 100Gi / 范围 10-500Gi, 见 deploy/cluster-prereq.sh step_template)。
            storage_size_gib: first.default_storage_size_gib,
            gpu_count: 0,
            efa_count: 0,
          });
        }
      })
      .catch((err) => {
        message.error(
          err instanceof ApiError
            ? err.message
            : t('create.messages.loadTemplatesFailed'),
        );
      })
      .finally(() => setLoadingTpl(false));

    // 可挂载列表 (FSx shared-pvcs + S3): 走抽出的 reloadMounts (见上), 与刷新按钮共用。
    reloadMounts();
  }, [form, message, wsId, cloneFrom, reloadMounts, t]);

  // When user switches template, reset dependent fields to its defaults.
  useEffect(() => {
    if (!selectedTemplate) return;
    // 克隆刚预填过 template_name → 本次 effect 触发, 但不能重置克隆的 image/storage。
    // 跳过一次并清标志, 之后用户手动切模板恢复正常重置行为。
    if (justClonedRef.current) {
      justClonedRef.current = false;
      return;
    }
    form.setFieldsValue({
      image: selectedTemplate.default_image,
      storage_size_gib: Math.min(
        Math.max(
          form.getFieldValue('storage_size_gib') ??
            selectedTemplate.default_storage_size_gib,
          selectedTemplate.min_storage_size_gib,
        ),
        selectedTemplate.max_storage_size_gib,
      ),
    });
  }, [selectedTemplate, form]);

  // 克隆: ?cloneFrom=<id> → 拉源开发机详情 → 预填表单 + env + 挂载选中。
  // 等 templates 与 mounts 都到位再跑 (要按 mount_path 匹配当前 ws 可挂载列表;
  // 且 template_name 要在 templates 列表里才能正确选中)。只跑一次 (cloneDoneRef)。
  const cloneDoneRef = useRef(false);
  useEffect(() => {
    if (!cloneFrom || cloneDoneRef.current) return;
    // 依赖数据未就绪则等下一轮 (templates/mounts 异步加载完会重触发本 effect)
    if (templates.length === 0 || loadingMounts) return;
    // cloneDoneRef 已保证只跑一次, 不用 cancelled 标志 (否则 clone 内 setState 触发
    // 重渲染 → effect 依赖变化 → 上一轮 cleanup 把 cancelled 置 true → finally 里
    // setCloneLoading(false) 被跳过 → 永远"加载中")。
    cloneDoneRef.current = true;
    (async () => {
      try {
        const d = await getDevInstance(cloneFrom);
        // 先置标志再 setFieldsValue: template_name 变化会触发切模板 effect, 让它跳过重置
        justClonedRef.current = true;
        form.setFieldsValue(mapDetailToFormValues(d));

        // 资源反查 (照训练 B 方案): 资源模板 (template_id) 是前端选值, 不落库 —
        // DevInstanceDetail 只有 gpu/cpu/mem 真值, 无 template_id。克隆只回填了
        // template_name (jupyter 模板), 不含资源模板 → ResourceSection 会默认选最小模板。
        // 这里用源实例的 gpu/cpu/mem 反查当前资源模板列表, 命中则预填 template_id +
        // 锁定规格 (grey band / 提交契约同源); 未命中提示重选。
        // 单位: 详情 cpu=millicores/mem=MiB → 模板 cpu_cores/mem_gib。
        const cpuCores = (d.cpu_request_millicores ?? 0) / 1000;
        const memGib = (d.memory_request_mib ?? 0) / 1024;
        try {
          const tpls = await listResourceTemplates(wsId);
          // mem 锁定下限 8 GiB (ResourceSection.applyTemplate 同规则), 反查时对齐:
          // 源实例内存可能被 max(,8) 抬过, 故先按模板原值比, 再兜底比抬到 8 后的值。
          const hit = tpls.find(
            (tpl) =>
              (tpl.resource.gpu ?? 0) === (d.gpu_count ?? 0) &&
              tpl.resource.cpu_cores === cpuCores &&
              (tpl.resource.mem_gib === memGib ||
                Math.max(tpl.resource.mem_gib ?? 0, 8) === memGib),
          );
          if (hit) {
            form.setFieldsValue({
              template_id: hit.template_id,
              gpu_count: hit.resource.gpu,
              efa_count: hit.resource.efa ?? 0,
              cpu_cores: hit.resource.cpu_cores,
              mem_gib: Math.max(hit.resource.mem_gib ?? 0, 8),
            });
          } else {
            message.warning(t('create.messages.cloneTemplateChanged'));
          }
        } catch {
          /* 资源模板反查失败不阻塞克隆 (ResourceSection 会给默认模板兜底) */
        }
        // env (dict) → EnvRow[]
        setEnvRows(
          Object.entries(d.env || {}).map(([key, value]) => ({
            key,
            value: String(value ?? ''),
          })),
        );
        // volume_mounts → 按 mount_path 匹配当前 ws 可挂载列表, 命中才选中
        // (源开发机挂的目录当前用户可能无权限/已删 → 匹配不上就跳过, 容错)。
        const fsxPaths: string[] = [];
        const s3Paths: string[] = [];
        for (const vm of d.volume_mounts || []) {
          const m = mounts.find((x) => x.mount_path === vm.mount_path);
          if (!m) continue;
          if (m.kind === 'fsx') fsxPaths.push(vm.mount_path);
          else s3Paths.push(vm.mount_path);
        }
        if (fsxPaths.length) setFsxSelectedPaths(fsxPaths);
        if (s3Paths.length) setS3SelectedPaths(s3Paths);
      } catch (err) {
        message.error(
          err instanceof ApiError
            ? err.message
            : t('create.messages.cloneFetchFailed'),
        );
      } finally {
        setCloneLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cloneFrom, templates, loadingMounts, mounts]);

  // mounts (合并) → 拆成 FSx/S3 两组 StorageItem 给 picker。id 用 mount_path (与提交一致)。
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

  const handleSubmit = async () => {
    try {
      await form.validateFields();
      const values = form.getFieldsValue(true);
      const env = envRows.reduce<Record<string, string>>((acc, row) => {
        if (row.key.trim()) acc[row.key.trim()] = row.value;
        return acc;
      }, {});
      // 不传 name, 后端按 mount_path slug 自动生成
      const allSelectedPaths = [...fsxSelectedPaths, ...s3SelectedPaths];
      const volume_mounts = allSelectedPaths.map((mp) => {
        const m = mounts.find((x) => x.mount_path === mp);
        if (!m) throw new Error(t('create.messages.mountMissing', { path: mp }));
        return { mount_path: mp, pvc_name: m.pvc_name };
      });
      const payload: DevInstanceCreatePayload = {
        name: values.name,
        display_name: values.display_name,
        description: values.description || undefined,
        template_name: values.template_name,
        image: values.image,
        // UI 核/GiB → 后端 millicores/MiB (1 核=1000m, 1 GiB=1024 MiB)
        cpu_request_millicores: Math.round((values.cpu_cores ?? 0) * 1000),
        memory_request_mib: Math.round((values.mem_gib ?? 0) * 1024),
        gpu_count: values.gpu_count ?? 0,
        efa_count: values.efa_count ?? 0,
        storage_size_gib: values.storage_size_gib,
        env,
        volume_mounts,
        // 资源池: 后端按 accelerators 展开成该池所有机型填 CR nodeAffinity
        pool: values.pool || undefined,
      };
      setSubmitting(true);
      await createDevInstance(wsId, payload);
      message.success(
        t('create.messages.created', { name: payload.display_name }),
      );
      navigate(`/workspaces/${wsId}/dev`);
    } catch (err) {
      if (err instanceof ApiError) message.error(err.message);
      // Form validation errors show inline; no extra toast.
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ProCard bordered>
      <Spin spinning={loadingTpl || cloneLoading} tip={cloneLoading ? t('create.loadingConfig') : undefined}>
        <Row gutter={24} wrap={false}>
          <Col flex="auto" style={{ minWidth: 0 }}>
            <Form form={form} layout="vertical" className="hp-create-form">
              <div id="dev-basic">
                <Typography.Title level={5}>{t('create.sections.basic')}</Typography.Title>
                <BasicSection />
              </div>
              <Divider />
              <div id="dev-template">
                <Typography.Title level={5}>{t('create.sections.template')}</Typography.Title>
                <TemplateSection
                  templates={templates}
                  selectedTemplateName={selectedTemplateName}
                />
              </div>
              <Divider />
              <div id="dev-image">
                <Typography.Title level={5}>{t('create.sections.image')}</Typography.Title>
                <ImageSection wsId={wsId} />
              </div>
              <Divider />
              <div id="dev-resource">
                <Typography.Title level={5}>{t('create.sections.resources')}</Typography.Title>
                <ResourceSection wsId={wsId} selectedTemplate={selectedTemplate} />
              </div>
              <Divider />
              <div id="dev-storage">
                <Typography.Title level={5}>
                  {t('fields.sharedStorage')}{' '}
                  <Tooltip title={t('create.storageTooltip')}>
                    <QuestionCircleOutlined
                      style={{ color: '#999', fontSize: 14 }}
                    />
                  </Tooltip>
                </Typography.Title>
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
              <Divider />
              <div id="dev-env">
                <Typography.Title level={5}>
                  {t('fields.envVars')}{' '}
                  <Tooltip title={t('create.envTooltip')}>
                    <QuestionCircleOutlined
                      style={{ color: '#999', fontSize: 14 }}
                    />
                  </Tooltip>
                </Typography.Title>
                <EnvSection envRows={envRows} onChange={setEnvRows} />
              </div>

              <Space style={{ marginTop: 24 }}>
                <Button
                  type="primary"
                  loading={submitting}
                  onClick={handleSubmit}
                >
                  {t('common:actions.create')}
                </Button>
                <Button onClick={() => navigate(`/workspaces/${wsId}/dev`)}>
                  {t('common:actions.cancel')}
                </Button>
              </Space>
            </Form>
          </Col>

          {/* 英文导航项更长 (Environment variables), 列宽 160 → 190 */}
          <Col flex="0 0 190px">
            <Anchor
              affix
              offsetTop={80}
              items={(
                [
                  ['basic', t('create.sections.basic')],
                  ['template', t('create.sections.template')],
                  ['image', t('create.sections.image')],
                  ['resource', t('create.sections.resources')],
                  ['storage', t('fields.sharedStorage')],
                  ['env', t('fields.envVars')],
                ] as const
              ).map(([key, label]) => ({
                key,
                href: `#dev-${key}`,
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
