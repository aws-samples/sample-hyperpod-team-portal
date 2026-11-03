import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Col, Form, InputNumber, Row, Select, theme, Tooltip, Typography } from 'antd';
import { InfoCircleOutlined, QuestionCircleOutlined } from '@ant-design/icons';
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
  watchedNodeCount: number | undefined;
  watchedReplicas: number | undefined;
  watchedGpuPerWorker: number | undefined;
  gpuOverQuota: boolean;
}

/**
 * 计算资源 (照推理 InstanceSection): 资源池 → 机型 → 资源模板 (锁单节点 gpu/cpu/mem/efa)。
 * 与推理差异: "副本数" → "节点数 (node_count)" (多机 multinode.nodeCount);
 * 总 GPU = node_count × 模板 gpu。模板 = 单 worker 节点规格 (同训练 gpu_per_node)。
 */
export default function InstanceSection({
  wsInstanceTypes,
  instTypePool,
  instTypeGpuSpec,
  allTemplates,
  remainingGpu,
  quotaTotalGpu,
  requestedGpu,
  watchedNodeCount,
  watchedReplicas,
  watchedGpuPerWorker,
  gpuOverQuota,
}: Props) {
  const { t } = useTranslation(['dynamo', 'common']);
  const form = Form.useFormInstance();
  const [pool, setPool] = useState<Pool>('gpu');
  const { token } = theme.useToken();

  useEffect(() => {
    const inPool = wsInstanceTypes.filter((ty) => instTypePool[ty] === pool);
    const cur = form.getFieldValue('instance_type');
    if (!cur || !inPool.includes(cur)) {
      form.setFieldValue('instance_type', inPool[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pool, wsInstanceTypes, instTypePool]);

  const watchedIt = Form.useWatch('instance_type', form);
  useEffect(() => {
    if (watchedIt && instTypePool[watchedIt] !== undefined) {
      setPool(instTypePool[watchedIt]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchedIt, instTypePool]);

  useEffect(() => {
    const inPool = allTemplates.filter((tpl) => templateInPool(tpl, pool));
    const cur = form.getFieldValue('template_id');
    if (!cur || !inPool.some((tpl) => tpl.template_id === cur)) {
      const smallest = pickSmallestTemplate(inPool);
      if (smallest) {
        const r = smallest.resource;
        form.setFieldsValue({
          template_id: smallest.template_id,
          gpu_per_worker: r.gpu,
          cpu_cores: r.cpu_cores,
          mem_gib: r.mem_gib,
          efa_per_worker: r.efa ?? 0,
        });
      } else {
        form.setFieldValue('template_id', undefined);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pool, allTemplates]);

  const watchedTplId = Form.useWatch('template_id', form);
  const selectedTpl = allTemplates.find((tpl) => tpl.template_id === watchedTplId);

  return (
    <>
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col span={5}>
          <Form.Item
            label={t('create.resource.poolLabel')}
            tooltip={t('create.resource.poolTooltip')}
            style={{ marginBottom: 0 }}
          >
            <Select style={{ width: '100%' }} options={POOL_OPTIONS} value={pool} onChange={(v) => setPool(v as Pool)} />
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
                  : t('create.resource.instanceTypePlaceholderEmpty')
              }
              notFoundContent={t('create.resource.instanceTypeNotFound')}
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
          <Form.Item
            name="template_id"
            label={t('create.resource.templateLabel')}
            rules={[{ required: true, message: t('create.resource.templateRequired') }]}
            tooltip={t('create.resource.templateTooltip')}
            style={{ marginBottom: 0 }}
          >
            <Select
              placeholder={t('create.resource.templatePlaceholder')}
              style={{ width: '100%' }}
              onChange={(tid) => {
                const tpl = allTemplates.find((item) => item.template_id === tid);
                if (!tpl) return;
                const r = tpl.resource;
                form.setFieldsValue({
                  gpu_per_worker: r.gpu,
                  cpu_cores: r.cpu_cores,
                  mem_gib: r.mem_gib,
                  efa_per_worker: r.efa ?? 0,
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
            name="node_count"
            label={t('create.resource.nodeCountLabel')}
            tooltip={t('create.resource.nodeCountTooltip')}
            rules={[{ required: true }]}
            style={{ marginBottom: 0 }}
          >
            <InputNumber min={1} max={64} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col span={18}>
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
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>
                  {t('create.resource.efaNote')}
                </Text>
              </span>
            </div>
          </Form.Item>
          {/* 锁定值绑进 form (hidden), 提交契约 */}
          <Form.Item name="gpu_per_worker" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          <Form.Item name="cpu_cores" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          <Form.Item name="mem_gib" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          <Form.Item name="efa_per_worker" hidden>
            <InputNumber />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginBottom: 8 }}>
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
      </Row>

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
              scale: t('spec.scale', {
                replicas: t('spec.replicaCount', { count: watchedReplicas ?? 1 }),
                nodes: t('spec.nodeCount', { count: watchedNodeCount ?? 1 }),
                gpu: t('spec.gpuCount', { count: watchedGpuPerWorker ?? 0 }),
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
      )}
    </>
  );
}
