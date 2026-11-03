import { useEffect } from 'react';
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
import { poolOfTemplate, templateInPool, type Pool } from '@/api/resource-pool';

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
  watchedNodes: number | undefined;
  watchedGpuPerPod: number | undefined;
  gpuOverQuota: boolean;
  onReloadTemplates?: () => void;
  templatesLoading?: boolean;
}

// 模板资源 (核/GiB) → 后端契约 (millicores/mib)
function applyTemplate(form: ReturnType<typeof Form.useFormInstance>, tpl: ResourceTemplateItem) {
  const r = tpl.resource;
  form.setFieldsValue({
    gpu_per_pod: r.gpu,
    efa_per_pod: r.efa ?? 0,
    cpu_request_millicores: Math.round(r.cpu_cores * 1000),
    cpu_limit_millicores: Math.round(r.cpu_cores * 1000),
    memory_request_mib: Math.round(r.mem_gib * 1024),
    memory_limit_mib: Math.round(r.mem_gib * 1024),
  });
}

export default function InstanceSection({
  wsInstanceTypes,
  instTypePool,
  instTypeGpuSpec,
  allTemplates,
  remainingGpu,
  quotaTotalGpu,
  requestedGpu,
  watchedReplicas,
  watchedNodes,
  watchedGpuPerPod,
  gpuOverQuota,
  onReloadTemplates,
  templatesLoading,
}: Props) {
  const { t } = useTranslation(['llmd', 'common']);
  const form = Form.useFormInstance();
  const { token } = theme.useToken();
  // llm-d worker 只跑 GPU 池 (机型 + 模板都按 gpu 池筛)
  const pool: Pool = 'gpu';
  const gpuTypes = wsInstanceTypes.filter((ty) => instTypePool[ty] === pool);

  // 无选中模板时默认选池内最小模板 + 同步隐藏资源字段
  useEffect(() => {
    const inPool = allTemplates.filter((tpl) => templateInPool(tpl, pool));
    const cur = form.getFieldValue('template_id');
    if (!cur || !inPool.some((tpl) => tpl.template_id === cur)) {
      const smallest = pickSmallestTemplate(inPool);
      if (smallest) {
        form.setFieldValue('template_id', smallest.template_id);
        applyTemplate(form, smallest);
      } else {
        form.setFieldValue('template_id', undefined);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allTemplates]);

  const watchedTplId = Form.useWatch('template_id', form);
  const selectedTpl = allTemplates.find((tpl) => tpl.template_id === watchedTplId);

  return (
    <>
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col span={8}>
          <Form.Item
            name="gpu_instance_type"
            label={t('create.resource.instanceTypeLabel')}
            tooltip={t('create.resource.instanceTypeTooltip')}
            rules={[{ required: true, message: t('create.resource.instanceTypeRequired') }]}
            style={{ marginBottom: 0 }}
          >
            <Select
              showSearch
              placeholder={
                gpuTypes.length
                  ? t('create.resource.instanceTypePlaceholder')
                  : t('create.resource.instanceTypePlaceholderEmpty')
              }
              notFoundContent={t('create.resource.instanceTypeNotFound')}
              options={gpuTypes.map((ty) => ({
                label: instTypeGpuSpec[ty] ? `${ty} (${instTypeGpuSpec[ty]})` : ty,
                value: ty,
              }))}
            />
          </Form.Item>
        </Col>
        <Col span={16}>
          {/* 外层 Form.Item 只管 label/tooltip; 内层 noStyle Form.Item 带 name 包住
              Select 以保留 form 绑定 (裸 div 做直接子元素会吃掉注入的 value/onChange
              → template_id 不进 form)。 */}
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
                    const tpl = allTemplates.find((item) => item.template_id === tid);
                    if (tpl) applyTemplate(form, tpl);
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
        <div style={{ fontSize: 12, lineHeight: '20px', marginBottom: 8, color: token.colorError }}>
          <InfoCircleOutlined style={{ marginRight: 6 }} />
          {t('create.resource.noTemplates')}
        </div>
      )}

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
        <Col span={6}>
          <Form.Item
            name="nodes_per_replica"
            label={t('create.resource.nodesLabel')}
            tooltip={t('create.resource.nodesTooltip')}
            rules={[{ required: true }]}
            style={{ marginBottom: 0 }}
          >
            <InputNumber min={2} max={64} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item
            label={
              <Text type="secondary" style={{ fontSize: 12, fontWeight: 'normal' }}>
                {t('create.resource.perNodeSpec')}
                <Tooltip title={t('create.resource.perNodeSpecTooltip')}>
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
              </span>
            </div>
          </Form.Item>
          {/* 模板锁定值绑进 form (hidden), 提交契约 */}
          <Form.Item name="gpu_per_pod" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          <Form.Item name="efa_per_pod" hidden>
            <InputNumber />
          </Form.Item>
          <Form.Item name="cpu_request_millicores" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          <Form.Item name="cpu_limit_millicores" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          <Form.Item name="memory_request_mib" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          <Form.Item name="memory_limit_mib" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
        </Col>
      </Row>

      <div
        style={{
          fontSize: 12,
          lineHeight: '20px',
          marginTop: 12,
          color: gpuOverQuota ? token.colorError : token.colorTextTertiary,
        }}
      >
        <InfoCircleOutlined style={{ marginRight: 6 }} />
        {t('create.resource.quotaNeed', { count: requestedGpu })}
        <Text style={{ fontSize: 12, color: 'inherit', opacity: 0.8 }}>
          {t('create.resource.quotaBreakdown', {
            scale: t('spec.scale', {
              replicas: t('spec.replicaCount', { count: watchedReplicas ?? 1 }),
              nodes: t('spec.nodeCount', { count: watchedNodes ?? 2 }),
              gpu: t('spec.gpuCount', { count: watchedGpuPerPod ?? 0 }),
            }),
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
    </>
  );
}
