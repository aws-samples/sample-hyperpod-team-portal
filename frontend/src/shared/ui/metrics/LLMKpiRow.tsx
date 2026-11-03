import { Col, Row, Tooltip } from 'antd';
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  MinusOutlined,
} from '@ant-design/icons';
import { useAppStore } from '@/store';
import { useCountUp } from '@/shared/hooks/useCountUp';

/* ============================================================================
 * LLM KPI strip — six hero numbers above the metrics grid.
 *
 * Uses a custom rAF count-up so the numbers settle in on first paint (instead
 * of just popping in) and a hover lift for the "premium dashboard" feel.
 * Colors respect semantic direction: latency going down is good (green),
 * throughput going up is good (green), anything else is neutral grey.
 * ========================================================================== */

interface Kpi {
  title: string;
  /** Numeric value driving the count-up animation. */
  numeric: number;
  /** Decimal places for the count-up output. */
  decimals: number;
  unit: string;
  trend: number;
  semantic: 'down-is-good' | 'up-is-good' | 'neutral';
  tooltip?: string;
}

const KPIS: Kpi[] = [
  {
    title: 'TTFT p50',
    numeric: 187,
    decimals: 0,
    unit: 'ms',
    trend: -3,
    semantic: 'down-is-good',
    tooltip: 'Time to first token (median)',
  },
  {
    title: 'TTFT p99',
    numeric: 420,
    decimals: 0,
    unit: 'ms',
    trend: 2,
    semantic: 'down-is-good',
  },
  {
    title: 'ITL avg',
    numeric: 52,
    decimals: 0,
    unit: 'ms/tok',
    trend: -1,
    semantic: 'down-is-good',
    tooltip: 'Inter-token latency average',
  },
  {
    title: 'Tokens/sec',
    numeric: 2340,
    decimals: 0,
    unit: 'tok/s',
    trend: 8,
    semantic: 'up-is-good',
  },
  {
    title: 'KV Cache',
    numeric: 67,
    decimals: 0,
    unit: '%',
    trend: 5,
    semantic: 'neutral',
    tooltip: 'GPU KV cache usage (>90% triggers alert)',
  },
  {
    title: 'QPS',
    numeric: 43.2,
    decimals: 1,
    unit: 'req/s',
    trend: 12,
    semantic: 'up-is-good',
  },
];

const trendColor = (trend: number, semantic: Kpi['semantic']): string => {
  if (trend === 0) return '#8c8c8c';
  const up = trend > 0;
  if (semantic === 'neutral') return '#8c8c8c';
  const good =
    (semantic === 'up-is-good' && up) ||
    (semantic === 'down-is-good' && !up);
  return good ? '#52c41a' : '#ff4d4f';
};

const trendIcon = (trend: number) => {
  if (trend > 0) return <ArrowUpOutlined />;
  if (trend < 0) return <ArrowDownOutlined />;
  return <MinusOutlined />;
};

export default function LLMKpiRow() {
  const themeMode = useAppStore((s) => s.themeMode);
  const isDark = themeMode === 'dark';

  const cardBg = isDark ? 'rgba(255,255,255,0.02)' : '#fff';
  const cardBorder = isDark ? 'rgba(255,255,255,0.08)' : '#f0f0f0';
  const titleColor = isDark ? 'rgba(255,255,255,0.55)' : '#8c8c8c';
  const numberColor = isDark ? 'rgba(255,255,255,0.92)' : '#1f1f1f';

  return (
    <Row gutter={[12, 12]}>
      {KPIS.map((k) => (
        <Col xs={12} sm={8} md={4} key={k.title}>
          <KpiCard
            kpi={k}
            cardBg={cardBg}
            cardBorder={cardBorder}
            titleColor={titleColor}
            numberColor={numberColor}
          />
        </Col>
      ))}
    </Row>
  );
}

/**
 * Individual KPI — isolated component so each value drives its own count-up
 * lifecycle; also simplifies the hover state with a local class.
 */
function KpiCard({
  kpi,
  cardBg,
  cardBorder,
  titleColor,
  numberColor,
}: {
  kpi: Kpi;
  cardBg: string;
  cardBorder: string;
  titleColor: string;
  numberColor: string;
}) {
  const animated = useCountUp(kpi.numeric, {
    decimals: kpi.decimals,
    durationMs: 420,
    thousand: true,
  });
  const color = trendColor(kpi.trend, kpi.semantic);

  const card = (
    <div
      className="kpi-card"
      style={{
        background: cardBg,
        border: `1px solid ${cardBorder}`,
        borderRadius: 10,
        padding: '16px 18px',
        height: '100%',
        transition: 'transform 250ms cubic-bezier(0.16, 1, 0.3, 1), box-shadow 250ms ease, border-color 250ms ease',
        cursor: 'default',
      }}
    >
      <div style={{ color: titleColor, fontSize: 12, marginBottom: 6 }}>
        {kpi.title}
      </div>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 6,
          marginBottom: 4,
        }}
      >
        <span
          style={{
            fontSize: 26,
            fontWeight: 600,
            color: numberColor,
            lineHeight: 1,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {animated}
        </span>
        <span style={{ color: titleColor, fontSize: 12 }}>{kpi.unit}</span>
      </div>
      <div style={{ color, fontSize: 12, fontWeight: 500 }}>
        {trendIcon(kpi.trend)} {Math.abs(kpi.trend)}% · 1h
      </div>
    </div>
  );
  return kpi.tooltip ? <Tooltip title={kpi.tooltip}>{card}</Tooltip> : card;
}
