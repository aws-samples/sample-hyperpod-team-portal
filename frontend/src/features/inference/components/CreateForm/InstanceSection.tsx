import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, Col, Form, InputNumber, Row, Select, theme, Tooltip, Typography } from 'antd';
import {
  InfoCircleOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import {
  pickSmallestTemplate,
  resourceText,
  type ResourceTemplateItem,
} from '@/api/resource-templates';
import {
  POOL_OPTIONS,
  poolOfTemplate,
  templateInPool,
  type Pool,
} from '@/api/resource-pool';

const { Text } = Typography;

interface Props {
  wsInstanceTypes: string[];
  instTypePool: Record<string, Pool>;
  instTypeGpuSpec: Record<string, string>;
  allTemplates: ResourceTemplateItem[];
  remainingGpu: number | null;
  quotaTotalGpu: number;
  requestedGpu: number;
  watchedReplicas: number | undefined;
  watchedGpuPerReplica: number | undefined;
  gpuOverQuota: boolean;
  onReloadTemplates?: () => void;
  templatesLoading?: boolean;
}

/**
 * 实例类型 (左) + 资源模板 (右) 并排 (原 step2 前半)。
 * 受控: 机型列表 / 模板列表由 index 下传; 选模板触发 form 资源字段填充 (req=lim)。
 * 顶部 GPU 余量提示照训练 ResourceSection: 本服务需 N 卡 (副本 × GPU) · 工作空间余量。
 */
export default function InstanceSection({
  wsInstanceTypes,
  instTypePool,
  instTypeGpuSpec,
  allTemplates,
  remainingGpu,
  quotaTotalGpu,
  requestedGpu,
  watchedReplicas,
  watchedGpuPerReplica,
  gpuOverQuota,
  onReloadTemplates,
  templatesLoading,
}: Props) {
  const { t } = useTranslation(['inference', 'common']);
  const form = Form.useFormInstance();
  // 资源池 (本地状态, 不进 payload)。初值跟随预填机型 (克隆), 否则 GPU
  const [pool, setPool] = useState<Pool>(() => {
    const it = form.getFieldValue('instance_type');
    return it && instTypePool[it] ? instTypePool[it] : 'gpu';
  });

  // 机型为空 (新建) 才填该池首个; 克隆已填 → 不动
  useEffect(() => {
    if (form.getFieldValue('instance_type')) return;
    const first = wsInstanceTypes.filter((ty) => instTypePool[ty] === pool)[0];
    if (first) form.setFieldValue('instance_type', first);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsInstanceTypes, instTypePool]);

  // 池跟随机型 (唯一自动方向; !== 守卫断反馈环)
  const watchedIt = Form.useWatch('instance_type', form);
  useEffect(() => {
    const p = watchedIt ? instTypePool[watchedIt] : undefined;
    if (p !== undefined && p !== pool) setPool(p);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchedIt, instTypePool]);

  // 切池/初始化: 当前模板不在新池 → 选该池最小模板 (req=lim 填充 gpu/cpu/mem)。
  // 避免默认选了不在当前池的模板 → Select 显示裸 template_id。
  useEffect(() => {
    const inPool = allTemplates.filter((tpl) => templateInPool(tpl, pool));
    const cur = form.getFieldValue('template_id');
    if (!cur || !inPool.some((tpl) => tpl.template_id === cur)) {
      const smallest = pickSmallestTemplate(inPool);
      if (smallest) {
        const r = smallest.resource;
        form.setFieldsValue({
          template_id: smallest.template_id,
          gpu_per_replica: r.gpu,
          cpu_request_cores: r.cpu_cores,
          cpu_limit_cores: r.cpu_cores,
          memory_request_gib: r.mem_gib,
          memory_limit_gib: r.mem_gib,
        });
      } else {
        form.setFieldsValue({ template_id: undefined });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pool, allTemplates]);

  // 选中的模板, 用于和"副本数"同行的灰带 (单副本规格只读展示)
  const watchedTplId = Form.useWatch('template_id', form);
  const selectedTpl = allTemplates.find((tpl) => tpl.template_id === watchedTplId);
  const { token } = theme.useToken();

  return (
    <>
      {/* ─── 1. 选择: 资源池 → 实例类型 → 资源模板 ─── */}
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col span={5}>
          <Form.Item
            label={t('create.resource.poolLabel')}
            tooltip={t('create.resource.poolTooltip')}
            style={{ marginBottom: 0 }}
          >
            <Select
              placeholder={t('create.resource.poolPlaceholder')}
              style={{ width: '100%' }}
              options={POOL_OPTIONS}
              value={pool}
              onChange={(v) => {
                // 用户主动切池才换机型 (唯一"池→机型"入口)
                const p = v as Pool;
                setPool(p);
                const first = wsInstanceTypes.filter((ty) => instTypePool[ty] === p)[0];
                form.setFieldValue('instance_type', first);
              }}
            />
          </Form.Item>
        </Col>
        <Col span={6}>
          <Form.Item
            name="instance_type"
            label={t('create.resource.instanceTypeLabel')}
            tooltip={t('create.resource.instanceTypeTooltip')}
            rules={[{ required: true, message: t('create.resource.instanceTypeRequired') }]}
            style={{ marginBottom: 0 }}
          >
            <Select
              showSearch
              placeholder={
                wsInstanceTypes.length
                  ? t('create.resource.instanceTypePlaceholder')
                  : t('create.resource.noAssignedTypes')
              }
              notFoundContent={t('create.resource.noTypesInPool')}
              options={wsInstanceTypes
                .filter((ty) => instTypePool[ty] === pool)
                .map((ty) => ({
                  label: instTypeGpuSpec[ty] ? `${ty} (${instTypeGpuSpec[ty]})` : ty,
                  value: ty,
                }))}
            />
          </Form.Item>
        </Col>
        <Col span={13}>
          {/* 外层 Form.Item 只管 label/tooltip; 内层 noStyle Form.Item 带 name 包住
              Select 以保留 form 绑定 (裸 div 包 Select 会吃掉 Form.Item 注入的
              value/onChange → template_id 永不更新 → 灰带按 template_id 读到旧模板)。 */}
          <Form.Item
            label={t('create.resource.templateLabel')}
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
                  onChange={(tid) => {
                    const picked = allTemplates.find((tpl) => tpl.template_id === tid);
                    if (!picked) return;
                    const r = picked.resource;
                    // 模板单值 → 推理 req=lim (同值填 request 与 limit)。
                    form.setFieldsValue({
                      gpu_per_replica: r.gpu,
                      cpu_request_cores: r.cpu_cores,
                      cpu_limit_cores: r.cpu_cores,
                      memory_request_gib: r.mem_gib,
                      memory_limit_gib: r.mem_gib,
                    });
                  }}
                  options={allTemplates
                    .filter((tpl) => templateInPool(tpl, pool))
                    .map((tpl) => ({
                      label: `${poolOfTemplate(tpl) === 'gpu' ? 'GPU' : 'CPU'} · ${resourceText(tpl.resource)} · ${tpl.name}`,
                      value: tpl.template_id,
                    }))}
                />
              </Form.Item>
              {onReloadTemplates && (
                <Tooltip title={t('common:actions.refresh')}>
                  <Button
                    type="text"
                    icon={<ReloadOutlined style={{ color: '#999' }} />}
                    loading={templatesLoading}
                    onClick={onReloadTemplates}
                  />
                </Tooltip>
              )}
            </div>
          </Form.Item>
        </Col>
      </Row>
      {allTemplates.length === 0 && (
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

      {/* ─── 2. 副本数 (左, 用户输入) + 模板锁定的单副本规格 (右, 单行只读灰带) ─── */}
      <Row gutter={16} align="bottom" style={{ marginBottom: 8, marginTop: 12 }}>
        <Col span={6}>
          <Form.Item
            name="replicas"
            label={t('create.resource.replicasLabel')}
            tooltip={t('create.resource.replicasTooltip')}
            rules={[{ required: true }]}
            style={{ marginBottom: 0 }}
          >
            <InputNumber min={1} max={256} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col span={18}>
          <Form.Item
            label={
              <Text type="secondary" style={{ fontSize: 12, fontWeight: 'normal' }}>
                {t('create.resource.perReplicaSpec')}
                <Tooltip title={t('create.resource.perReplicaSpecTooltip')}>
                  <QuestionCircleOutlined style={{ color: '#999', marginLeft: 6, cursor: 'help' }} />
                </Tooltip>
              </Text>
            }
            colon={false}
            style={{ marginBottom: 0 }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                // 英文单位 (cards / cores / adapters) 更长: 间距 24 → 16, 放不下时整块换行 (每块自身不拆)
                gap: 16,
                minHeight: 32,
                flexWrap: 'wrap',
                rowGap: 4,
                padding: '0 12px',
                borderRadius: token.borderRadius,
                background: token.colorFillTertiary,
                border: `1px solid ${token.colorBorderSecondary}`,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              <span style={{ whiteSpace: 'nowrap' }}>
                <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>GPU</Text>
                <Text strong>{selectedTpl ? selectedTpl.resource.gpu : '—'}</Text>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>
                  {t('spec.unitCard', { count: selectedTpl ? selectedTpl.resource.gpu : 0 })}
                </Text>
              </span>
              <span style={{ width: 1, height: 14, background: token.colorBorderSecondary }} />
              <span style={{ whiteSpace: 'nowrap' }}>
                <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>CPU</Text>
                <Text strong>{selectedTpl ? selectedTpl.resource.cpu_cores : '—'}</Text>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>
                  {t('spec.unitCore', { count: selectedTpl ? selectedTpl.resource.cpu_cores : 0 })}
                </Text>
              </span>
              <span style={{ width: 1, height: 14, background: token.colorBorderSecondary }} />
              <span style={{ whiteSpace: 'nowrap' }}>
                <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>{t('spec.memory')}</Text>
                <Text strong>{selectedTpl ? selectedTpl.resource.mem_gib : '—'}</Text>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>GiB</Text>
              </span>
              <span style={{ width: 1, height: 14, background: token.colorBorderSecondary }} />
              <span style={{ whiteSpace: 'nowrap' }}>
                <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>EFA</Text>
                <Text strong>{selectedTpl ? (selectedTpl.resource.efa ?? 0) : '—'}</Text>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>
                  {t('spec.unitAdapter', { count: selectedTpl ? (selectedTpl.resource.efa ?? 0) : 0 })}
                </Text>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>
                  {t('create.resource.efaNote')}
                </Text>
              </span>
            </div>
          </Form.Item>
          {/* 锁定值仍绑进 form, hidden InputNumber 保提交契约 (req=lim 同值) */}
          <Form.Item name="gpu_per_replica" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          <Form.Item name="cpu_request_cores" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          <Form.Item name="cpu_limit_cores" hidden>
            <InputNumber />
          </Form.Item>
          <Form.Item name="memory_request_gib" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          <Form.Item name="memory_limit_gib" hidden>
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
            marginBottom: 12,
            color: gpuOverQuota ? token.colorError : token.colorTextTertiary,
          }}
        >
          <InfoCircleOutlined style={{ marginRight: 6 }} />
          {t('create.resource.quotaNeed', { count: requestedGpu })}
          <Text style={{ fontSize: 12, color: 'inherit', opacity: 0.8 }}>
            {t('create.resource.quotaBreakdown', {
              count: watchedReplicas ?? 1,
              gpu: t('spec.gpuCount', { count: watchedGpuPerReplica ?? 0 }),
            })}
          </Text>
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

      {/* ─── 4. 容器端口 (与资源面板独立, 但仍属本 step) ─── */}
      <Row gutter={16}>
        <Col span={8}>
          <Form.Item
            name="container_port"
            label={t('create.resource.containerPortLabel')}
            tooltip={t('create.resource.containerPortTooltip')}
            rules={[{ required: true }]}
          >
            <InputNumber min={1} max={65535} style={{ width: 120 }} />
          </Form.Item>
        </Col>
      </Row>
    </>
  );
}
