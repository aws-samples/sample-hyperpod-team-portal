/**
 * 机型配额选择器 (创建 ws + 调整配额共用) · 方案 B 改版.
 *
 * 受控组件: 通过 antd Form.List name 绑定, 父级 <Form> 提供 form 实例.
 * 拉集群机型清单 + 所有 ws 已占, 算每机型"可分给本 ws 的剩余":
 *   剩余 = 集群该机型总台数 − 所有 ws 已占 + 本 ws 已占
 *   (创建场景 currentQuotaId 不传 → 本 ws 已占=0 → 退化为 总数−所有已占)
 *
 * UI: 不再"加一行/选机型/填数量"3 步走, 而是把整个集群机型铺成清单, 每机型一行,
 *     按 GPU / CPU 池分组, 数量框 0=未分配 / >0=已选, 顶部一条汇总. 提交前在
 *     submit 处把 count==0 的行剔掉 (Dashboard.handleSaveQuota / List 创建逻辑里自带空过滤).
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Empty,
  Form,
  Input,
  InputNumber,
  Skeleton,
  Typography,
} from 'antd';
import {
  listClusters,
  listInstanceGroups,
  type InstanceGroupRaw,
} from '@/features/admin/api/cluster';
import { listClusterQuotas, type ComputeQuota } from '@/features/quota/api';

const { Text } = Typography;

/** 单条机型配额行 (Form.List item). */
export interface QuotaResourceRow {
  instance_type: string;
  count: number;
}

/** 集群机型聚合 + 剩余容量. */
export interface ClusterTypeCapacity {
  instance_type: string;
  cluster_total: number;
  used_by_other_ws: number;
  remaining: number;
  gpu_count: number;
  gpu_type: string | null;
}

/**
 * 纯函数: 算每机型剩余.
 *
 * @param groups 集群 InstanceGroup 原始列表 (同 type 多 group 累加 CurrentCount)
 * @param allQuotas 集群所有 ws 的 quota (含本 ws)
 * @param currentQuotaId 编辑时传当前 ws quotaId → 把它的占用加回剩余; 创建不传
 */
export function computeTypeCapacity(
  groups: InstanceGroupRaw[],
  allQuotas: ComputeQuota[],
  currentQuotaId?: string,
): ClusterTypeCapacity[] {
  const totals = new Map<string, number>();
  const gpuCountByType = new Map<string, number>();
  const gpuTypeByType = new Map<string, string | null>();
  for (const g of groups) {
    const t = g.InstanceType;
    totals.set(t, (totals.get(t) ?? 0) + (g.CurrentCount ?? 0));
    if (!gpuCountByType.has(t)) {
      gpuCountByType.set(t, g.gpu_count ?? 0);
      gpuTypeByType.set(t, g.gpu_type ?? null);
    }
  }
  const usedAll = new Map<string, number>();
  const usedSelf = new Map<string, number>();
  for (const q of allQuotas) {
    const isSelf = currentQuotaId != null && q.computeQuotaId === currentQuotaId;
    for (const r of q.resources) {
      usedAll.set(r.instanceType, (usedAll.get(r.instanceType) ?? 0) + r.count);
      if (isSelf) {
        usedSelf.set(
          r.instanceType,
          (usedSelf.get(r.instanceType) ?? 0) + r.count,
        );
      }
    }
  }
  return Array.from(totals.entries())
    .map(([instance_type, cluster_total]) => {
      const all = usedAll.get(instance_type) ?? 0;
      const self = usedSelf.get(instance_type) ?? 0;
      const used_by_other_ws = all - self;
      return {
        instance_type,
        cluster_total,
        used_by_other_ws,
        remaining: Math.max(cluster_total - used_by_other_ws, 0),
        gpu_count: gpuCountByType.get(instance_type) ?? 0,
        gpu_type: gpuTypeByType.get(instance_type) ?? null,
      };
    })
    .sort((a, b) => a.instance_type.localeCompare(b.instance_type));
}

interface QuotaResourcePickerProps {
  /** 集群 tag (= ClusterName) · 不传则 fallback listClusters()[0] (单集群部署) */
  clusterTag?: string;
  /** Form.List 字段名 (默认 'resources') */
  name?: string;
  /** 编辑时传当前 ws quotaId · 剩余容量把自己已占加回 */
  currentQuotaId?: string;
}

export default function QuotaResourcePicker({
  clusterTag,
  name = 'resources',
  currentQuotaId,
}: QuotaResourcePickerProps) {
  // 原始集群数据 (机型组 + 所有 ws 配额): 只随 clusterTag 异步拉一次。
  const [raw, setRaw] = useState<{
    groups: InstanceGroupRaw[];
    quotas: ComputeQuota[];
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const { t } = useTranslation(['quota']);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        let tag = clusterTag;
        if (!tag) {
          const clusters = await listClusters();
          tag = clusters[0]?.cluster_tag;
        }
        if (!tag) {
          if (!cancelled && raw === null) setRaw({ groups: [], quotas: [] });
          return;
        }
        const [groups, quotaList] = await Promise.all([
          listInstanceGroups(tag),
          listClusterQuotas(tag).catch(() => null),
        ]);
        if (cancelled) return;
        setRaw({
          groups: groups as InstanceGroupRaw[],
          quotas: quotaList?.quotas ?? [],
        });
      } catch {
        if (!cancelled && raw === null) setRaw({ groups: [], quotas: [] });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clusterTag]);

  // currentQuotaId 变化 (本 ws 已占加回) 走纯计算重算, 不重发请求。
  const clusterTypes = useMemo<ClusterTypeCapacity[]>(
    () =>
      raw
        ? computeTypeCapacity(raw.groups, raw.quotas, currentQuotaId)
        : [],
    [raw, currentQuotaId],
  );

  // 还没拉到任何数据 (raw===null, 含首帧 effect 未跑 + 加载中) 或正在加载 → 显骨架,
  // 不显"暂无机型" banner。否则: ① 首帧 loading 还是 false + raw 为空会闪一下 banner;
  // ② 切集群重拉的空窗期也会闪。只有"已拉到数据 + 确实为空"才显 banner。
  if (raw === null || loading) {
    return <Skeleton active paragraph={{ rows: 4 }} />;
  }
  if (clusterTypes.length === 0) {
    return (
      <Alert
        type="warning"
        showIcon
        message={t('picker.noTypesTitle')}
        description={t('picker.noTypesDesc')}
        style={{ marginBottom: 16 }}
      />
    );
  }

  // 每个机型在 resources 数组里的固定索引 = 它在 clusterTypes (已排序) 里的位置。
  // SyncListWithCluster 严格按 clusterTypes 顺序填充 resources, 故此 index 即数组位置,
  // 不必从 getFieldValue 反查 (反查在"填充 effect 还没跑完"时拿不到 → N/A)。
  const rowIndexByType = new Map<string, number>();
  clusterTypes.forEach((ct, i) => rowIndexByType.set(ct.instance_type, i));

  const filtered = clusterTypes.filter((ct) =>
    keyword.trim()
      ? ct.instance_type.toLowerCase().includes(keyword.trim().toLowerCase())
      : true,
  );
  const gpuTypes = filtered.filter((ct) => ct.gpu_count > 0);
  const cpuTypes = filtered.filter((ct) => ct.gpu_count <= 0);

  return (
    <Form.List name={name}>
      {() => (
        <>
          {/* 按 clusterTypes 顺序原子填充 resources 行 (effect) */}
          <SyncListWithCluster clusterTypes={clusterTypes} name={name} />

          <SummaryBar clusterTypes={clusterTypes} name={name} />

          <Input.Search
            allowClear
            placeholder={t('picker.searchPlaceholder')}
            style={{ marginBottom: 12 }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />

          {filtered.length === 0 && (
            <Empty description={t('picker.noMatch')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}

          {gpuTypes.length > 0 && (
            <PoolSection
              title={t('picker.gpuPool')}
              color="#1677ff"
              description={t('picker.gpuPoolDesc')}
              types={gpuTypes}
              rowIndexByType={rowIndexByType}
              name={name}
            />
          )}
          {cpuTypes.length > 0 && (
            <PoolSection
              title={t('picker.cpuPool')}
              color="#52c41a"
              description={t('picker.cpuPoolDesc')}
              types={cpuTypes}
              rowIndexByType={rowIndexByType}
              name={name}
            />
          )}
        </>
      )}
    </Form.List>
  );
}

/* ────────────────────── 内部组件 ────────────────────── */

interface SyncProps {
  clusterTypes: ClusterTypeCapacity[];
  name: string;
}

/**
 * 用 effect 把 Form.List 的行同步成"每机型一行": 集群有但 form 没有 → add({count:0}).
 * 取消"删行"概念 (用户置 0 即可); 提交时父级过滤 count<=0 行.
 */
function SyncListWithCluster({ clusterTypes, name }: SyncProps) {
  const form = Form.useFormInstance();
  // 机型集合稳定 key: 只在集合真正变化时重排 (不随数组引用每渲染变化反复触发)。
  const typesKey = clusterTypes
    .map((t) => t.instance_type)
    .sort()
    .join(',');
  useEffect(() => {
    if (clusterTypes.length === 0) {
      form.setFieldValue(name, []); // 集群无机型 / 未选 → 清空, 不残留旧集群机型
      return;
    }
    // 原子 setFieldValue 重排整列: 已有机型沿用其 count, 缺的补 count=0, 不在新集群
    // 的旧机型自动丢弃。PoolSection 按 getFieldValue 的行索引绑定 (非 Form.List fields),
    // 故 setFieldValue 一次到位即可渲染出数量框 (不再依赖 add 的时序)。
    const rows: QuotaResourceRow[] = form.getFieldValue(name) ?? [];
    const byType = new Map(
      rows.filter((r) => r?.instance_type).map((r) => [r.instance_type, r]),
    );
    const next: QuotaResourceRow[] = clusterTypes.map(
      (t) =>
        byType.get(t.instance_type) ?? { instance_type: t.instance_type, count: 0 },
    );
    form.setFieldValue(name, next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typesKey]);
  return null;
}

interface SummaryProps {
  clusterTypes: ClusterTypeCapacity[];
  name: string;
}

function SummaryBar({ name, clusterTypes }: SummaryProps) {
  const { t } = useTranslation(['quota']);
  // 用 Form.useWatch 拿实时 rows, 数量变更立刻更新汇总
  const form = Form.useFormInstance();
  const rows = (Form.useWatch(name, form) ?? []) as QuotaResourceRow[];
  const gpuCountByType = new Map(
    clusterTypes.map((ct) => [ct.instance_type, ct.gpu_count]),
  );
  const isGpuType = (type: string) => (gpuCountByType.get(type) ?? 0) > 0;

  const selected = rows.filter((r) => r?.instance_type && (r.count ?? 0) > 0);
  const gpuRows = selected.filter((r) => isGpuType(r.instance_type));
  const cpuRows = selected.filter((r) => !isGpuType(r.instance_type));
  const gpuCount = gpuRows.reduce((s, r) => s + (r.count ?? 0), 0);
  const cpuCount = cpuRows.reduce((s, r) => s + (r.count ?? 0), 0);
  const gpuCards = gpuRows.reduce(
    (s, r) => s + (r.count ?? 0) * (gpuCountByType.get(r.instance_type) ?? 0),
    0,
  );

  // 行式 stat: label 灰色小字 + 数字主色粗体, 等宽数字, 不再用 Alert/Tag
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'baseline',
        gap: 32,
        padding: '12px 4px',
        marginBottom: 12,
        borderBottom: '1px solid rgba(5,5,5,0.06)',
      }}
    >
      <Stat
        label={t('picker.summary.selectedTypes')}
        value={`${selected.length}`}
        unit={t('picker.summary.typeUnit', { count: selected.length })}
      />
      <Stat
        label={t('picker.gpuPool')}
        value={gpuRows.length === 0 ? '—' : `${gpuCount}`}
        unit={gpuRows.length === 0 ? '' : t('picker.summary.instanceUnit', { count: gpuCount })}
        secondary={
          gpuRows.length === 0 ? null : t('picker.summary.cardsUnit', { count: gpuCards })
        }
        accent={gpuRows.length > 0 ? '#1677ff' : undefined}
      />
      <Stat
        label={t('picker.cpuPool')}
        value={cpuRows.length === 0 ? '—' : `${cpuCount}`}
        unit={cpuRows.length === 0 ? '' : t('picker.summary.instanceUnit', { count: cpuCount })}
        accent={cpuRows.length > 0 ? '#52c41a' : undefined}
      />
      <Text type="secondary" style={{ fontSize: 12, marginLeft: 'auto' }}>
        {t('picker.summary.hint')}
      </Text>
    </div>
  );
}

function Stat({
  label,
  value,
  unit,
  secondary,
  accent,
}: {
  label: string;
  value: string;
  unit?: string;
  secondary?: string | null;
  accent?: string;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
      <Text type="secondary" style={{ fontSize: 11, letterSpacing: 0.4 }}>
        {label}
      </Text>
      <span style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span
          style={{
            fontSize: 18,
            fontWeight: 600,
            fontVariantNumeric: 'tabular-nums',
            color: accent ?? 'rgba(0,0,0,0.85)',
          }}
        >
          {value}
        </span>
        {unit && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {unit}
          </Text>
        )}
        {secondary && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            · {secondary}
          </Text>
        )}
      </span>
    </div>
  );
}

interface PoolSectionProps {
  title: string;
  color: string;
  description: string;
  types: ClusterTypeCapacity[];
  /** 机型 → 在 resources 数组里的固定行索引 (= clusterTypes 顺序位置) */
  rowIndexByType: Map<string, number>;
  name: string;
}

function PoolSection({
  title,
  color,
  description,
  types,
  rowIndexByType,
  name,
}: PoolSectionProps) {
  const { t } = useTranslation(['quota']);
  const form = Form.useFormInstance();
  // 用 Form.useWatch 拿实时 rows: 既驱动选中态视觉, 也保证 setFieldValue 填充后重渲染。
  const rows = (Form.useWatch(name, form) ?? []) as QuotaResourceRow[];

  return (
    <div style={{ marginTop: 20 }}>
      {/* Section header: 左色条 (4px) + 标题 + 副标题, 取代原来的 Tag */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          paddingLeft: 8,
          marginBottom: 8,
          borderLeft: `3px solid ${color}`,
        }}
      >
        <Text strong style={{ fontSize: 13, letterSpacing: 0.3 }}>
          {title}
        </Text>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {description}
        </Text>
      </div>

      <div>
        {/* table header — 仅留下边线, 去灰底 */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 150px 130px 150px',
            padding: '8px 12px 8px 12px',
            fontSize: 11,
            fontWeight: 500,
            letterSpacing: 0.4,
            textTransform: 'uppercase',
            color: 'rgba(0,0,0,0.45)',
            borderBottom: '1px solid rgba(5,5,5,0.06)',
          }}
        >
          <span style={{ whiteSpace: 'nowrap' }}>{t('picker.columns.instanceType')}</span>
          <span style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{t('picker.columns.remainingTotal')}</span>
          <span style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{t('picker.columns.gpuPerInstance')}</span>
          <span style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{t('picker.columns.allocated')}</span>
        </div>

        {types.map((ct) => {
          // 固定行索引 (clusterTypes 顺序位置), 一定存在; 不依赖 form 当前是否已填充。
          const fieldIdx = rowIndexByType.get(ct.instance_type);
          const count = rows[fieldIdx ?? -1]?.count ?? 0;
          const gpu = ct.gpu_type;
          const accel = ct.gpu_count;
          const isSelected = (count ?? 0) > 0;
          const remaining = ct.remaining;
          return (
            <div
              key={ct.instance_type}
              style={{
                position: 'relative',
                display: 'grid',
                gridTemplateColumns: '1fr 150px 130px 150px',
                alignItems: 'center',
                padding: '12px 12px',
                borderBottom: '1px solid rgba(5,5,5,0.04)',
                background: isSelected ? `${color}0A` : undefined, // ~4% alpha
                transition: 'background 120ms ease',
              }}
            >
              {/* 选中态左色条 (2px), 取代 Badge dot */}
              {isSelected && (
                <span
                  aria-hidden
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: 2,
                    background: color,
                  }}
                />
              )}

              <span style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <Text
                  style={{
                    fontSize: 14,
                    fontVariantNumeric: 'tabular-nums',
                    color: isSelected ? 'rgba(0,0,0,0.85)' : 'rgba(0,0,0,0.75)',
                  }}
                >
                  {ct.instance_type}
                </Text>
                {gpu && (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    · {gpu}
                  </Text>
                )}
              </span>

              {/* 剩余 / 总: 主数字粗 + 分母弱; 0/0 整段红 */}
              <span
                style={{
                  textAlign: 'right',
                  fontVariantNumeric: 'tabular-nums',
                  fontSize: 13,
                  color: remaining === 0 ? '#ff4d4f' : 'rgba(0,0,0,0.85)',
                }}
              >
                <span style={{ fontWeight: 600 }}>{remaining}</span>
                <span style={{ color: 'rgba(0,0,0,0.40)', fontWeight: 400 }}>
                  {' '}/ {ct.cluster_total}
                </span>
              </span>

              <span
                style={{
                  textAlign: 'right',
                  fontVariantNumeric: 'tabular-nums',
                  fontSize: 13,
                  color: accel > 0 ? 'rgba(0,0,0,0.65)' : 'rgba(0,0,0,0.30)',
                }}
              >
                {accel > 0 ? `${accel} GPU` : '—'}
              </span>

              <div style={{ textAlign: 'right' }}>
                {fieldIdx !== undefined ? (
                  // 用 fieldIdx (来自 getFieldValue 的 rows 索引) 直接绑, 不依赖
                  // Form.List 的 fields 数组 —— fields 有时跟不上 getFieldValue,
                  // 用 fields.find 会拿不到 → 数量框显 N/A。按位置 name 绑则稳。
                  <Form.Item
                    name={[fieldIdx, 'count']}
                    style={{ marginBottom: 0 }}
                    rules={[
                      { type: 'number', min: 0, message: t('picker.nonNegative') },
                    ]}
                  >
                    <InputNumber
                      min={0}
                      max={remaining}
                      style={{ width: 110 }}
                      placeholder="0"
                      controls={false}
                    />
                  </Form.Item>
                ) : (
                  <Text type="secondary" style={{ fontSize: 12 }}>N/A</Text>
                )}
              </div>

              {/* hidden instance_type 字段, 保 Form.List 项数据完整 */}
              {fieldIdx !== undefined && (
                <Form.Item name={[fieldIdx, 'instance_type']} hidden>
                  <input />
                </Form.Item>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
