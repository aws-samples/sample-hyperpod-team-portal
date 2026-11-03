import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, Col, Form, Input, InputNumber, Row, Select, Switch, theme, Tooltip, Typography } from 'antd';
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
import ScriptEditor from '@/features/training/components/CreateForm/ScriptEditor';

const { Text } = Typography;

interface Props {
  allTemplates: ResourceTemplateItem[];
  wsInstanceTypes: string[];
  instTypePool: Record<string, Pool>;
  instTypeGpuSpec: Record<string, string>;
  onReloadTemplates?: () => void;
  templatesLoading?: boolean;
}

// 模板资源 (核/GiB) → gateway 后端契约 (millicores/mib); request=limit (无状态路由不留余量)。
function applyGatewayTemplate(
  form: ReturnType<typeof Form.useFormInstance>,
  tpl: ResourceTemplateItem,
) {
  const r = tpl.resource;
  form.setFieldsValue({
    gateway_cpu_request_millicores: Math.round(r.cpu_cores * 1000),
    gateway_cpu_limit_millicores: Math.round(r.cpu_cores * 1000),
    gateway_memory_request_mib: Math.round(r.mem_gib * 1024),
    gateway_memory_limit_mib: Math.round(r.mem_gib * 1024),
  });
}

/**
 * Gateway (sgl-model-gateway) 段: 镜像 + CPU 资源模板 (纯 CPU 路由, 不吃 GPU) + 副本 + 额外参数。
 * 资源模板走 CPU 池, 带出 gateway cpu/内存 (隐藏字段, 提交契约)。gateway 落 worker 同 GPU 机不占 GPU 配额。
 */
export default function GatewaySection({
  allTemplates,
  wsInstanceTypes,
  instTypePool,
  instTypeGpuSpec,
  onReloadTemplates,
  templatesLoading,
}: Props) {
  const { t } = useTranslation(['llmd', 'common']);
  const form = Form.useFormInstance();
  const { token } = theme.useToken();
  const pool: Pool = 'cpu';

  // 无选中模板时默认选 CPU 池内最小模板 + 同步隐藏资源字段
  useEffect(() => {
    const inPool = allTemplates.filter((tpl) => templateInPool(tpl, pool));
    const cur = form.getFieldValue('gateway_template_id');
    if (!cur || !inPool.some((tpl) => tpl.template_id === cur)) {
      const smallest = pickSmallestTemplate(inPool);
      if (smallest) {
        form.setFieldValue('gateway_template_id', smallest.template_id);
        applyGatewayTemplate(form, smallest);
      } else {
        form.setFieldValue('gateway_template_id', undefined);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allTemplates]);

  const watchedTplId = Form.useWatch('gateway_template_id', form);
  const selectedTpl = allTemplates.find((tpl) => tpl.template_id === watchedTplId);

  return (
    <>
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col span={24}>
          <Form.Item
            name="gateway_image"
            label={t('create.gateway.imageLabel')}
            tooltip={t('create.gateway.imageTooltip')}
            rules={[{ required: true, message: t('create.gateway.imageRequired') }]}
            style={{ marginBottom: 0 }}
          >
            <Input placeholder="lmsysorg/sgl-model-gateway:latest" />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col span={24}>
          <Form.Item
            name="gateway_instance_type"
            label={t('create.gateway.instanceTypeLabel')}
            tooltip={t('create.gateway.instanceTypeTooltip')}
            rules={[{ required: true, message: t('create.gateway.instanceTypeRequired') }]}
            style={{ marginBottom: 0 }}
          >
            <Select
              showSearch
              placeholder={
                wsInstanceTypes.length
                  ? t('create.gateway.instanceTypePlaceholder')
                  : t('create.gateway.instanceTypePlaceholderEmpty')
              }
              notFoundContent={t('create.gateway.instanceTypeNotFound')}
              options={wsInstanceTypes.map((ty) => ({
                label:
                  (instTypePool[ty] === 'gpu' ? 'GPU · ' : 'CPU · ') +
                  (instTypeGpuSpec[ty] ? `${ty} (${instTypeGpuSpec[ty]})` : ty),
                value: ty,
              }))}
            />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={16} align="bottom" style={{ marginBottom: 8 }}>
        <Col span={12}>
          {/* 外层 Form.Item 只管 label/tooltip; 内层 noStyle Form.Item 带 name 包住
              Select 以保留 form 绑定 (裸 div 做直接子元素会吃掉注入的 value/onChange
              → gateway_template_id 不进 form)。 */}
          <Form.Item
            label={t('create.gateway.templateLabel')}
            required
            tooltip={t('create.gateway.templateTooltip')}
            style={{ marginBottom: 0 }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <Form.Item
                name="gateway_template_id"
                noStyle
                rules={[{ required: true, message: t('create.gateway.templateRequired') }]}
              >
                <Select
                  placeholder={t('create.gateway.templatePlaceholder')}
                  style={{ flex: 1 }}
                  onChange={(tid) => {
                    const tpl = allTemplates.find((item) => item.template_id === tid);
                    if (tpl) applyGatewayTemplate(form, tpl);
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
        <Col span={12}>
          <Form.Item
            label={
              <Text type="secondary" style={{ fontSize: 12, fontWeight: 'normal' }}>
                {t('create.gateway.specLabel')}
                <Tooltip title={t('create.gateway.specTooltip')}>
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
                gap: 20,
                height: 32,
                padding: '0 12px',
                borderRadius: token.borderRadius,
                background: token.colorFillTertiary,
                border: `1px solid ${token.colorBorderSecondary}`,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              <span>
                <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>CPU</Text>
                <Text strong>{selectedTpl ? selectedTpl.resource.cpu_cores : '—'}</Text>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>
                  {t('spec.unitCore', { count: selectedTpl ? selectedTpl.resource.cpu_cores : 0 })}
                </Text>
              </span>
              <span style={{ width: 1, height: 14, background: token.colorBorderSecondary }} />
              <span>
                <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>{t('spec.memory')}</Text>
                <Text strong>{selectedTpl ? selectedTpl.resource.mem_gib : '—'}</Text>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>GiB</Text>
              </span>
            </div>
          </Form.Item>
          {/* 模板锁定值绑进 form (hidden), 提交契约 */}
          <Form.Item name="gateway_cpu_request_millicores" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          <Form.Item name="gateway_cpu_limit_millicores" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          <Form.Item name="gateway_memory_request_mib" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          <Form.Item name="gateway_memory_limit_mib" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
        </Col>
      </Row>
      {allTemplates.filter((tpl) => templateInPool(tpl, pool)).length === 0 && (
        <div style={{ fontSize: 12, lineHeight: '20px', marginBottom: 8, color: token.colorError }}>
          <InfoCircleOutlined style={{ marginRight: 6 }} />
          {t('create.gateway.noTemplates')}
        </div>
      )}

      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col span={8}>
          <Form.Item
            name="gateway_replicas"
            label={t('create.gateway.replicasLabel')}
            tooltip={t('create.gateway.replicasTooltip')}
            rules={[{ required: true }]}
            style={{ marginBottom: 0 }}
          >
            <InputNumber min={1} max={16} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col span={24}>
          <Form.Item
            name="expose_alb"
            valuePropName="checked"
            label={t('create.gateway.exposeAlbLabel')}
            tooltip={t('create.gateway.exposeAlbTooltip')}
            style={{ marginBottom: 0 }}
          >
            <Switch
              checkedChildren={t('create.gateway.on')}
              unCheckedChildren={t('create.gateway.off')}
            />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginBottom: 8 }}>
        <Col span={24}>
          <Form.Item
            name="gateway_extra_args"
            label={t('create.gateway.extraArgsLabel')}
            tooltip={t('create.gateway.extraArgsTooltip')}
            extra={t('create.gateway.extraArgsExtra')}
            style={{ marginBottom: 0 }}
          >
            <ScriptEditor height={120} language="shell" langLabel="Args" />
          </Form.Item>
        </Col>
      </Row>
    </>
  );
}
