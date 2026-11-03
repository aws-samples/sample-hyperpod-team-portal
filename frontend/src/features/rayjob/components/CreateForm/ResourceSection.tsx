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

// role → form 字段名映射 (head/worker 各一套独立字段)
interface RoleFields {
  instanceType: string;
  templateId: string;
  gpu: string;
  cpuCores: string;
  memGib: string;
  efa: string;
}
export const HEAD_FIELDS: RoleFields = {
  instanceType: 'head_instance_type',
  templateId: 'head_template_id',
  gpu: 'head_gpu',
  cpuCores: 'head_cpu_cores',
  memGib: 'head_mem_gib',
  efa: 'head_efa',
};
export const WORKER_FIELDS: RoleFields = {
  instanceType: 'worker_instance_type',
  templateId: 'worker_template_id',
  gpu: 'gpu_per_node',
  cpuCores: 'cpu_per_node_cores',
  memGib: 'memory_per_node_gib',
  efa: 'efa_per_node',
};

export interface ResourceSectionProps {
  fields: RoleFields;
  defaultPool: Pool;
  wsInstanceTypes: string[];
  instTypePool: Record<string, Pool>;
  instTypeGpuSpec: Record<string, string>;
  allTemplates: ResourceTemplateItem[];
}

/**
 * 计算资源单块 (head 或 worker, 由 fields/defaultPool 参数化)。
 * 资源池 + 实例类型 + 资源模板(锁 gpu/cpu/mem), 各自 nodeSelector 锁机型。
 * head 默认 CPU 池 (协调节点省 GPU), worker 默认 GPU 池 (计算节点)。
 */
export default function ResourceSection({
  fields,
  defaultPool,
  wsInstanceTypes,
  instTypePool,
  instTypeGpuSpec,
  allTemplates,
}: ResourceSectionProps) {
  const { t } = useTranslation('rayjob');
  const form = Form.useFormInstance();
  // pool 初值跟随预填机型 (克隆), 否则 defaultPool
  const [pool, setPool] = useState<Pool>(() => {
    const it = form.getFieldValue(fields.instanceType);
    return it && instTypePool[it] ? instTypePool[it] : defaultPool;
  });

  // 机型为空 (新建) 才填该池首个; 克隆已填 → 不动
  useEffect(() => {
    if (form.getFieldValue(fields.instanceType)) return;
    const first = wsInstanceTypes.filter((it) => instTypePool[it] === pool)[0];
    if (first) form.setFieldValue(fields.instanceType, first);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsInstanceTypes, instTypePool]);

  // 池跟随机型 (唯一自动方向; !== 守卫断反馈环)
  const watchedIt = Form.useWatch(fields.instanceType, form);
  useEffect(() => {
    const p = watchedIt ? instTypePool[watchedIt] : undefined;
    if (p !== undefined && p !== pool) setPool(p);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchedIt, instTypePool]);

  useEffect(() => {
    const inPool = allTemplates.filter((tpl) => templateInPool(tpl, pool));
    const cur = form.getFieldValue(fields.templateId);
    if (!cur || !inPool.some((tpl) => tpl.template_id === cur)) {
      const smallest = pickSmallestTemplate(inPool);
      form.setFieldsValue(
        smallest
          ? {
              [fields.templateId]: smallest.template_id,
              [fields.gpu]: smallest.resource.gpu,
              [fields.cpuCores]: smallest.resource.cpu_cores,
              [fields.memGib]: smallest.resource.mem_gib,
              [fields.efa]: smallest.resource.efa ?? 0,
            }
          : { [fields.templateId]: undefined },
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pool, allTemplates]);

  const watchedTplId = Form.useWatch(fields.templateId, form);
  const selectedTpl = allTemplates.find((tpl) => tpl.template_id === watchedTplId);
  const { token } = theme.useToken();

  return (
    <>
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
                const first = wsInstanceTypes.filter((it) => instTypePool[it] === p)[0];
                form.setFieldValue(fields.instanceType, first);
              }}
            />
          </Form.Item>
        </Col>
        <Col span={6}>
          <Form.Item
            name={fields.instanceType}
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
                .filter((it) => instTypePool[it] === pool)
                .map((it) => ({
                  label: instTypeGpuSpec[it] ? `${it} (${instTypeGpuSpec[it]})` : it,
                  value: it,
                }))}
            />
          </Form.Item>
        </Col>
        <Col span={13}>
          <Form.Item
            name={fields.templateId}
            label={t('create.resource.templateLabel')}
            rules={[{ required: true, message: t('create.resource.templateRequired') }]}
            tooltip={t('create.resource.templateTooltip')}
            style={{ marginBottom: 0 }}
          >
            <Select
              placeholder={t('create.resource.templatePlaceholder')}
              style={{ width: '100%' }}
              onChange={(tid) => {
                const tpl = allTemplates.find((x) => x.template_id === tid);
                if (!tpl) return;
                form.setFieldsValue({
                  [fields.gpu]: tpl.resource.gpu,
                  [fields.cpuCores]: tpl.resource.cpu_cores,
                  [fields.memGib]: tpl.resource.mem_gib,
                  [fields.efa]: tpl.resource.efa ?? 0,
                });
              }}
              options={allTemplates
                .filter((x) => templateInPool(x, pool))
                .map((x) => ({
                  label: `${poolOfTemplate(x) === 'gpu' ? 'GPU' : 'CPU'} · ${resourceText(x.resource)} · ${x.name}`,
                  value: x.template_id,
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
        style={{ marginBottom: 0, marginTop: 8 }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 24,
            height: 32,
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
            <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>
              {t('spec.unitCard', { count: Number(selectedTpl?.resource.gpu) || 0 })}
            </Text>
          </span>
          <span style={{ width: 1, height: 14, background: token.colorBorderSecondary }} />
          <span>
            <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>CPU</Text>
            <Text strong>{selectedTpl ? selectedTpl.resource.cpu_cores : '—'}</Text>
            <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>
              {t('spec.unitCore', { count: Number(selectedTpl?.resource.cpu_cores) || 0 })}
            </Text>
          </span>
          <span style={{ width: 1, height: 14, background: token.colorBorderSecondary }} />
          <span>
            <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>
              {t('spec.memory')}
            </Text>
            <Text strong>{selectedTpl ? selectedTpl.resource.mem_gib : '—'}</Text>
            <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>GiB</Text>
          </span>
          <span style={{ width: 1, height: 14, background: token.colorBorderSecondary }} />
          <span>
            <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>EFA</Text>
            <Text strong>{selectedTpl ? (selectedTpl.resource.efa ?? 0) : '—'}</Text>
            <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>
              {t('spec.unitAdapter', { count: Number(selectedTpl?.resource.efa) || 0 })}
            </Text>
          </span>
        </div>
      </Form.Item>
      <Form.Item name={fields.gpu} hidden rules={[{ required: true }]}>
        <InputNumber />
      </Form.Item>
      <Form.Item name={fields.cpuCores} hidden rules={[{ required: true }]}>
        <InputNumber />
      </Form.Item>
      <Form.Item name={fields.memGib} hidden rules={[{ required: true }]}>
        <InputNumber />
      </Form.Item>
      <Form.Item name={fields.efa} hidden>
        <InputNumber />
      </Form.Item>
    </>
  );
}
