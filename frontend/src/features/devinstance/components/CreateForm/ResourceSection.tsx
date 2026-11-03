import { useCallback, useEffect, useState } from 'react';
import { Button, Col, Form, InputNumber, Row, Select, theme, Tooltip, Typography } from 'antd';
import { InfoCircleOutlined, ReloadOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type { TemplateInfo } from '../../api/types';
import {
  listResourceTemplates,
  pickSmallestTemplate,
  resourceText,
  type ResourceTemplateItem,
} from '@/api/resource-templates';
import {
  aggregateQuota,
  getWorkspaceQuota,
  getWorkspaceQuotaUsage,
} from '@/features/quota/api';
import {
  POOL_OPTIONS,
  poolOfTemplate,
  templateInPool,
  type Pool,
} from '@/api/resource-pool';

const { Text } = Typography;

interface Props {
  wsId: string;
  selectedTemplate: TemplateInfo | undefined;
}

/**
 * 资源：选资源模板 (统一一套, admin 管) → 自动填 GPU/CPU/内存, 用户不可手填。
 * 2026-06-14 确定: 三类共用一套模板; 用户只能选, 资源字段锁定。
 * EBS 存储不在模板内, 仍可填。
 *
 * 约束：HyperPod ValidatingAdmissionPolicy 硬拦 memory < 8 GiB (Remote Access 前置)。
 */
export default function ResourceSection({ wsId, selectedTemplate }: Props) {
  const { t } = useTranslation(['devinstance', 'common']);
  const form = Form.useFormInstance();
  const [templates, setTemplates] = useState<ResourceTemplateItem[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  // GPU 配额提示 (照训练/推理): 总量 + 已用量 → 余量。
  const [quotaTotalGpu, setQuotaTotalGpu] = useState<number>(0);
  const [usageUsedGpu, setUsageUsedGpu] = useState<number>(-1);
  // 该 ws 各池实际有哪些机型 (来自 quota.resources[].pool, 后端 EC2 GpuInfo 权威判)。
  // 用于拦"选了某池但该 ws 该池无机型"→ 否则后端展开池机型为空, Pod 永远 Pending。
  // null = 还没拉到配额 (不下结论, 不误报)。
  const [poolTypes, setPoolTypes] = useState<Record<Pool, string[]> | null>(null);

  // 资源池 (开发机只选池): 默认 GPU, GPU 模板为空则回退 CPU。
  const pool = (Form.useWatch('pool', form) as Pool | undefined) ?? 'gpu';

  const refresh = useCallback(() => {
    if (!wsId) return;
    setRefreshing(true);
    listResourceTemplates(wsId)
      .then((list) => {
        setTemplates(list);
        // 默认池: GPU; 若无 GPU 模板则回退 CPU。
        if (!form.getFieldValue('pool')) {
          const hasGpu = list.some((tpl) => (tpl.resource.gpu ?? 0) > 0);
          form.setFieldValue('pool', hasGpu ? 'gpu' : 'cpu');
        }
        // 默认选该池最小配置模板 (未选时自动应用)。
        if (!form.getFieldValue('template_id')) {
          const curPool: Pool = form.getFieldValue('pool') ?? 'gpu';
          const inPool = list.filter((tpl) => templateInPool(tpl, curPool));
          const smallest = pickSmallestTemplate(inPool);
          if (smallest) {
            const r = smallest.resource;
            form.setFieldsValue({
              template_id: smallest.template_id,
              gpu_count: r.gpu,
              efa_count: r.efa ?? 0,
              cpu_cores: r.cpu_cores,
              mem_gib: Math.max(r.mem_gib ?? 0, 8),
            });
          }
        }
      })
      .catch(() => setTemplates([]))
      .finally(() => setRefreshing(false));
  }, [wsId, form]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // 拉 ws 配额: GPU 总量/已用量 (余量提示)。失败不阻塞 (余量提示降级)。
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
        // 按 pool 归类该 ws 配额里的机型 (pool 由后端 quota.resources[].pool 给)。
        const byPool: Record<Pool, string[]> = { gpu: [], cpu: [] };
        for (const r of q.value.resources) {
          const p: Pool = r.pool === 'gpu' ? 'gpu' : 'cpu';
          if (r.instanceType) byPool[p].push(r.instanceType);
        }
        setPoolTypes(byPool);
      }
      if (u.status === 'fulfilled') {
        setUsageUsedGpu(u.value.totals.accelerators);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [wsId]);

  // 切池: 当前模板不在新池 → 重选该池最小模板 (同步锁定的 gpu/cpu/mem)。
  useEffect(() => {
    const inPool = templates.filter((tpl) => templateInPool(tpl, pool));
    const cur = form.getFieldValue('template_id');
    if (cur && !inPool.some((tpl) => tpl.template_id === cur)) {
      const smallest = pickSmallestTemplate(inPool);
      form.setFieldsValue(
        smallest
          ? {
              template_id: smallest.template_id,
              gpu_count: smallest.resource.gpu,
              efa_count: smallest.resource.efa ?? 0,
              cpu_cores: smallest.resource.cpu_cores,
              mem_gib: Math.max(smallest.resource.mem_gib ?? 0, 8),
            }
          : { template_id: undefined },
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pool, templates]);

  const applyTemplate = (tid: string) => {
    const tpl = templates.find((x) => x.template_id === tid);
    if (!tpl) return;
    const r = tpl.resource;
    form.setFieldsValue({
      gpu_count: r.gpu,
      efa_count: r.efa ?? 0,
      cpu_cores: r.cpu_cores,
      mem_gib: Math.max(r.mem_gib ?? 0, 8), // 内存策略下限 8 GiB
    });
  };

  // 选中的模板, 用于和"存储"同行的灰带 (单节点规格只读展示)
  const watchedTplId = Form.useWatch('template_id', form);
  const selectedTpl = templates.find((tpl) => tpl.template_id === watchedTplId);
  const { token } = theme.useToken();

  // GPU 余量提示 (照训练/推理): 开发机单节点, 需求 = gpu_count。
  // 优先取选中模板的真实卡数 (灰带同源, 无 useWatch 首帧时序差); gpu_count watch 兜底。
  // 直接用 watchedGpu 会因 hidden 字段 setFieldsValue 后 useWatch 首帧未到 → 显示 0。
  const watchedGpu = Form.useWatch('gpu_count', form);
  const requestedGpu = selectedTpl?.resource.gpu ?? watchedGpu ?? 0;
  const remainingGpu = usageUsedGpu < 0 ? null : Math.max(0, quotaTotalGpu - usageUsedGpu);
  const gpuOverQuota = remainingGpu !== null && requestedGpu > remainingGpu;

  // 当前选的池在该 ws 有没有机型: poolTypes 拉到 (非 null) 且该池机型列表为空 → 无机型。
  // 此时即使有模板也不能起 (后端展开池机型为空 → Pod 永远 Pending), 必须拦提交。
  const poolHasNoTypes =
    poolTypes !== null && (poolTypes[pool]?.length ?? 0) === 0;

  return (
    <>
      {/* ─── 1. 选择: 资源池 → (无实例类型) → 资源模板 ─── */}
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col span={6}>
          {/* 资源池 (开发机只选池): 选 CPU 则后端展开成该 ws 所有 CPU 机型填 CR */}
          <Form.Item
            name="pool"
            label={t('fields.resourcePool')}
            tooltip={t('create.resource.poolTooltip')}
            rules={[{ required: true, message: t('create.resource.poolRequired') }]}
            style={{ marginBottom: 0 }}
          >
            <Select
              placeholder={t('create.resource.poolPlaceholder')}
              style={{ width: '100%' }}
              options={POOL_OPTIONS}
            />
          </Form.Item>
        </Col>
        <Col span={18}>
          {/* 资源模板 (统一一套, 仅 admin 管, 用户只能选) */}
          {/* 外层 Form.Item 只管 label/tooltip; 内层 noStyle Form.Item 带 name 包住
              Select 以保留 form 绑定 (裸 div 做直接子元素会吃掉注入的 value/onChange
              → template_id 不进 form)。 */}
          <Form.Item
            label={t('fields.resourceTemplate')}
            required
            tooltip={t('create.resource.templateTooltip')}
            style={{ marginBottom: 0 }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <Form.Item
                name="template_id"
                noStyle
                rules={[{ required: true, message: t('create.resource.templateRequired') }]}
              >
                <Select
                  placeholder={t('create.resource.templatePlaceholder')}
                  style={{ flex: 1 }}
                  onChange={(tid) => tid && applyTemplate(tid)}
                  options={templates
                    .filter((tpl) => templateInPool(tpl, pool))
                    .map((tpl) => ({
                      label: `${poolOfTemplate(tpl) === 'gpu' ? 'GPU' : 'CPU'} · ${resourceText(tpl.resource)} · ${tpl.name}`,
                      value: tpl.template_id,
                    }))}
                />
              </Form.Item>
              <Tooltip title={t('common:actions.refresh')}>
                <Button
                  type="text"
                  icon={<ReloadOutlined style={{ color: '#999' }} />}
                  loading={refreshing}
                  onClick={refresh}
                />
              </Tooltip>
            </div>
          </Form.Item>
        </Col>
      </Row>
      {templates.length === 0 && (
        <div
          style={{
            fontSize: 12,
            lineHeight: '20px',
            marginBottom: 8,
            color: token.colorError,
          }}
        >
          <InfoCircleOutlined style={{ marginRight: 6 }} />
          {t('create.resource.noTemplates')}
        </div>
      )}

      {/* 选了某池但该 ws 该池无机型: 纯文字一行红色提示 (同"本次需 N 卡"风格) + 拦提交 */}
      {poolHasNoTypes && (
        <div
          style={{
            fontSize: 12,
            lineHeight: '20px',
            marginBottom: 8,
            color: token.colorError,
          }}
        >
          <InfoCircleOutlined style={{ marginRight: 6 }} />
          {t('create.resource.poolNoTypes', { pool: pool === 'gpu' ? 'GPU' : 'CPU' })}
        </div>
      )}
      {/* 隐藏校验字段: 该池无机型时校验失败 → 提交被 validateFields 拦下 */}
      <Form.Item
        name="__pool_has_types"
        hidden
        rules={[
          {
            validator: async () => {
              if (poolHasNoTypes) {
                throw new Error(t('create.resource.poolNoTypesValidator'));
              }
            },
          },
        ]}
      >
        <input />
      </Form.Item>

      {/* ─── 2. 存储 (左, 用户输入) + 模板锁定的单节点规格 (右, 单行只读灰带) ─── */}
      {/* align=top: 两列顶端对齐, label 与 输入框/灰带 同行 (存储下方 extra 范围提示
          不影响上方对齐; 用 bottom 会被 extra 撑得错位) */}
      <Row gutter={16} align="top" style={{ marginBottom: 8, marginTop: 12 }}>
        <Col span={6}>
          <Form.Item
            name="storage_size_gib"
            label={t('create.resource.storageLabel')}
            tooltip={t('create.resource.storageTooltip')}
            extra={
              selectedTemplate
                ? t('create.resource.range', {
                    min: selectedTemplate.min_storage_size_gib,
                    max: selectedTemplate.max_storage_size_gib,
                  })
                : t('create.resource.rangeDefault')
            }
            rules={[{ required: true }]}
            style={{ marginBottom: 0 }}
          >
            <InputNumber
              min={selectedTemplate?.min_storage_size_gib ?? 1}
              max={selectedTemplate?.max_storage_size_gib ?? 100}
              step={1}
              addonAfter="GiB"
              style={{ width: '100%' }}
            />
          </Form.Item>
        </Col>
        <Col span={18}>
          <Form.Item
            label={t('create.resource.perNodeSpec')}
            tooltip={t('create.resource.perNodeSpecTooltip')}
            colon={false}
            style={{ marginBottom: 0 }}
          >
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
              <span>
                <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>GPU</Text>
                <Text strong>{selectedTpl ? selectedTpl.resource.gpu : '—'}</Text>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>{t('spec.unitCard', { count: Number(selectedTpl?.resource.gpu) || 0 })}</Text>
              </span>
              <span style={{ width: 1, height: 14, background: token.colorBorderSecondary }} />
              <span>
                <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>CPU</Text>
                <Text strong>{selectedTpl ? selectedTpl.resource.cpu_cores : '—'}</Text>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>{t('spec.unitCore', { count: Number(selectedTpl?.resource.cpu_cores) || 0 })}</Text>
              </span>
              <span style={{ width: 1, height: 14, background: token.colorBorderSecondary }} />
              <span>
                <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>{t('spec.memory')}</Text>
                <Text strong>{selectedTpl ? selectedTpl.resource.mem_gib : '—'}</Text>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>GiB</Text>
              </span>
              <span style={{ width: 1, height: 14, background: token.colorBorderSecondary }} />
              <span>
                <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>EFA</Text>
                <Text strong>{selectedTpl ? (selectedTpl.resource.efa ?? 0) : '—'}</Text>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>{t('spec.unitAdapter', { count: Number(selectedTpl?.resource.efa) || 0 })}</Text>
              </span>
            </div>
          </Form.Item>
          {/* 锁定值仍绑进 form, hidden InputNumber 保提交契约 */}
          <Form.Item name="gpu_count" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          {/* EFA: 模板带出, 无 required (0 也是合法值; 大部分模板无 EFA) */}
          <Form.Item name="efa_count" hidden>
            <InputNumber />
          </Form.Item>
          <Form.Item name="cpu_cores" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          <Form.Item
            name="mem_gib"
            hidden
            rules={[
              { required: true },
              {
                validator: async (_r, v) => {
                  if (v != null && v < 8) {
                    throw new Error(t('create.resource.memoryPolicy'));
                  }
                },
              },
            ]}
          >
            <InputNumber />
          </Form.Item>
        </Col>
      </Row>

      {/* ─── 3. 配额提示: 纯文字一行 (无背景框, 淡灰小字; 超额关键字转红) ───
          仅 GPU 池显示 (GPU 卡余量约束); CPU 池无 GPU 概念, 隐藏避免误导。 */}
      {pool === 'gpu' && (
        <div
          style={{
            fontSize: 12,
            lineHeight: '20px',
            marginBottom: 8,
            color: gpuOverQuota ? token.colorError : token.colorTextTertiary,
          }}
        >
          <InfoCircleOutlined style={{ marginRight: 6 }} />
          {t('create.resource.quotaNeed', { count: requestedGpu })}
          {remainingGpu !== null ? (
            <>
              {t('create.resource.quotaRemaining', {
                remaining: remainingGpu,
                count: quotaTotalGpu,
              })}
              {gpuOverQuota && t('create.resource.quotaOver')}
            </>
          ) : (
            t('create.resource.quotaCollecting', { count: quotaTotalGpu })
          )}
        </div>
      )}
    </>
  );
}
