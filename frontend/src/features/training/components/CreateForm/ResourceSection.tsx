import { useEffect, useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import {
  Button,
  Col,
  Form,
  InputNumber,
  Radio,
  Row,
  Select,
  theme,
  Tooltip,
  Typography,
} from 'antd';
import {
  InfoCircleOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { ProCard } from '@ant-design/pro-components';
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
import PriorityTag from '@/shared/ui/PriorityTag';
import { getTopologyLevels } from '../../api/client';
import type { TopologyLevel } from '../../api/types';

const { Text } = Typography;

export interface ResourceSectionProps {
  wsId: string;
  wsInstanceTypes: string[];
  instTypePool: Record<string, Pool>;
  instTypeGpuSpec: Record<string, string>;
  allTemplates: ResourceTemplateItem[];
  remainingGpu: number | null;
  quotaTotalGpu: number;
  requestedGpu: number;
  watchedNodeCount: number | undefined;
  watchedGpuPerNode: number | undefined;
  gpuOverQuota: boolean;
  onReloadTemplates?: () => void;
  templatesLoading?: boolean;
}

/**
 * 计算资源 (原 step2): 配额 bar + 实例类型 + 资源模板(锁 gpu/cpu/mem) +
 * 节点数 + 拓扑感知调度 (TAS)。
 * instance_type/template_id/node_count/gpu/cpu/mem/topology_* 绑 form;
 * 配额/模板列表/机型列表由 index 经 props 传。
 */
export default function ResourceSection({
  wsId,
  wsInstanceTypes,
  instTypePool,
  instTypeGpuSpec,
  allTemplates,
  remainingGpu,
  quotaTotalGpu,
  requestedGpu,
  watchedNodeCount,
  watchedGpuPerNode,
  gpuOverQuota,
  onReloadTemplates,
  templatesLoading,
}: ResourceSectionProps) {
  const { t } = useTranslation(['training', 'common']);
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

  const [topoLevels, setTopoLevels] = useState<TopologyLevel[]>([]);
  const [topoLoading, setTopoLoading] = useState(false);
  // 查询失败要与"真的没有层级"分开显示: 否则 RBAC 缺权限的 403 会伪装成"无可选层级"
  const [topoError, setTopoError] = useState<string | null>(null);
  useEffect(() => {
    if (!wsId || !watchedIt) {
      setTopoLevels([]);
      setTopoError(null);
      return;
    }
    let cancelled = false;
    setTopoLoading(true);
    setTopoError(null);
    getTopologyLevels(wsId, watchedIt)
      .then((levels) => {
        if (cancelled) return;
        setTopoLevels(levels);
        // 换机型后已选层级可能不在新列表里 → 清掉, 否则提交必被后端 400 拦
        const cur = form.getFieldValue('topology_label');
        if (cur && !levels.some((lv) => lv.node_label === cur)) {
          form.setFieldValue('topology_label', undefined);
        }
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setTopoLevels([]);
        setTopoError(e instanceof Error ? e.message : t('create.resource.topology.queryFailed'));
      })
      .finally(() => {
        if (!cancelled) setTopoLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId, watchedIt]);

  // 切池/初始化: 当前模板不在新池 → 选该池最小模板 (同步锁定的 gpu/cpu/mem)。
  // 避免默认选了不在当前池的模板 → Select 显示裸 template_id。
  useEffect(() => {
    const inPool = allTemplates.filter((tpl) => templateInPool(tpl, pool));
    const cur = form.getFieldValue('template_id');
    if (!cur || !inPool.some((tpl) => tpl.template_id === cur)) {
      const smallest = pickSmallestTemplate(inPool);
      form.setFieldsValue(
        smallest
          ? {
              template_id: smallest.template_id,
              gpu_per_node: smallest.resource.gpu,
              cpu_per_node_cores: smallest.resource.cpu_cores,
              memory_per_node_gib: smallest.resource.mem_gib,
              efa_per_node: smallest.resource.efa ?? 0, // 老模板无 efa → 0
            }
          : { template_id: undefined },
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pool, allTemplates]);

  // 选中的模板 (用于和"节点数"同行的灰带, 单行只读展示锁定的单节点规格)
  const watchedTplId = Form.useWatch('template_id', form);
  const selectedTpl = allTemplates.find((tpl) => tpl.template_id === watchedTplId);
  const { token } = theme.useToken();

  return (
    <>
      {/* ─── 1. 选择: 资源池 → 实例类型 → 资源模板 (用户的输入) ─── */}
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col span={5}>
          <Form.Item
            label={t('fields.resourcePool')}
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
            label={t('fields.instanceType')}
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
                  onChange={(tid) => {
                    const tpl = allTemplates.find((x) => x.template_id === tid);
                    if (!tpl) return;
                    form.setFieldsValue({
                      gpu_per_node: tpl.resource.gpu,
                      cpu_per_node_cores: tpl.resource.cpu_cores,
                      memory_per_node_gib: tpl.resource.mem_gib,
                      efa_per_node: tpl.resource.efa ?? 0, // 老模板无 efa → 0
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

      {/* ─── 2. 节点数 (左, 用户输入) + 模板锁定的单节点规格 (右, 单行只读灰带) ─── */}
      {/* span 与上一行逐列对齐: 节点数↔资源池(5) · 额外节点↔实例类型(6) · 规格↔资源模板(13) */}
      <Row gutter={16} align="bottom" style={{ marginBottom: 8, marginTop: 12 }}>
        <Col span={5}>
          <Form.Item
            name="node_count"
            label={t('fields.nodeCount')}
            tooltip={t('create.resource.nodeCountTooltip')}
            rules={[{ required: true, message: t('create.resource.nodeCountRequired') }]}
            style={{ marginBottom: 0 }}
          >
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col span={6}>
          <Form.Item
            name="spares"
            label={t('fields.spares')}
            tooltip={t('create.resource.sparesTooltip')}
            style={{ marginBottom: 0 }}
          >
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col span={13}>
          {/* 灰带和"节点数"同高度: 用空 label 占同一行, 单行展示 GPU/CPU/内存 */}
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
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>{t('spec.unitCard', { count: Number(selectedTpl?.resource.gpu) || 0 })}</Text>
              </span>
              <span style={{ width: 1, height: 14, background: token.colorBorderSecondary }} />
              <span style={{ whiteSpace: 'nowrap' }}>
                <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>CPU</Text>
                <Text strong>{selectedTpl ? selectedTpl.resource.cpu_cores : '—'}</Text>
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>{t('spec.unitCore', { count: Number(selectedTpl?.resource.cpu_cores) || 0 })}</Text>
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
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>{t('spec.unitAdapter', { count: Number(selectedTpl?.resource.efa) || 0 })}</Text>
              </span>
            </div>
          </Form.Item>
          {/* 锁定值仍绑进 form, hidden InputNumber 保提交契约 */}
          <Form.Item name="gpu_per_node" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          <Form.Item name="cpu_per_node_cores" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          <Form.Item name="memory_per_node_gib" hidden rules={[{ required: true }]}>
            <InputNumber />
          </Form.Item>
          {/* EFA 数也由模板锁定 (不再手填), hidden 保提交契约; 老模板 → 0。 */}
          <Form.Item name="efa_per_node" hidden>
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
          <Text style={{ fontSize: 12, color: 'inherit', opacity: 0.8 }}>
            {t('create.resource.quotaBreakdown', {
              count: watchedNodeCount ?? 1,
              gpu: t('spec.gpuCount', { count: watchedGpuPerNode ?? 0 }),
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

      {/* 拓扑感知调度 · Kueue TAS 注解, 仅 p5+/trn 节点真生效 */}
      <ProCard
        title={
          <span>
            {t('create.resource.topology.title')}
            <Tooltip
              title={
                <span>
                  {t('create.resource.topology.help')}
                  <br />
                  <br />
                  {t('create.resource.topology.annotation')}
                  <br />
                  <code>kueue.x-k8s.io/podset-{'{mode}'}-topology=&lt;label&gt;</code>
                </span>
              }
            >
              <QuestionCircleOutlined style={{ color: '#999', marginLeft: 6, cursor: 'help' }} />
            </Tooltip>
          </span>
        }
        bordered
        style={{ marginTop: 16 }}
        bodyStyle={{ padding: 12 }}
        headerBordered
      >
        <Form.Item
          name="topology_mode"
          label={t('create.resource.topology.modeLabel')}
          tooltip={t('create.resource.topology.modeTooltip')}
          style={{ marginBottom: 12 }}
        >
          <Radio.Group optionType="button" buttonStyle="solid">
            <Radio.Button value="none">{t('create.resource.topology.modeNone')}</Radio.Button>
            <Radio.Button value="preferred">
              {t('create.resource.topology.modePreferred')}
            </Radio.Button>
            <Radio.Button value="required">
              {t('create.resource.topology.modeRequired')}
            </Radio.Button>
          </Radio.Group>
        </Form.Item>
        <Form.Item shouldUpdate={(p, c) => p.topology_mode !== c.topology_mode} noStyle>
          {({ getFieldValue }) => {
            const mode = getFieldValue('topology_mode');
            const disabled = !mode || mode === 'none';
            return (
              <Form.Item
                name="topology_label"
                label={t('create.resource.topology.levelLabel')}
                tooltip={t('create.resource.topology.levelTooltip')}
                style={{ marginBottom: 0 }}
                extra={
                  disabled || topoLoading ? undefined : topoError ? (
                    <Text type="danger" style={{ fontSize: 12 }}>
                      {t('create.resource.topology.levelQueryFailed', { error: topoError })}
                    </Text>
                  ) : topoLevels.length === 0 ? (
                    t('create.resource.topology.noLevels')
                  ) : undefined
                }
              >
                <Select
                  disabled={disabled || topoLoading || topoLevels.length === 0}
                  loading={topoLoading}
                  placeholder={
                    disabled
                      ? t('create.resource.topology.pickModeFirst')
                      : topoError
                        ? t('create.resource.topology.queryFailed')
                        : topoLevels.length === 0
                          ? t('create.resource.topology.noLevelsShort')
                          : t('create.resource.topology.pickLevel')
                  }
                  allowClear
                  style={{ width: '100%', maxWidth: 560 }}
                  options={topoLevels.map((lv) => ({
                    label: `${lv.display_name} · ${lv.node_label}`,
                    value: lv.node_label,
                  }))}
                />
              </Form.Item>
            );
          }}
        </Form.Item>
      </ProCard>

      <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
        <Trans
          i18nKey="create.resource.priorityDefault"
          ns="training"
          components={{ tag: <PriorityTag priorityClass="common-priority" /> }}
        />
        <Tooltip title={t('create.resource.priorityTooltip')}>
          <QuestionCircleOutlined style={{ color: '#999', marginLeft: 6, cursor: 'help' }} />
        </Tooltip>
      </Text>
    </>
  );
}
