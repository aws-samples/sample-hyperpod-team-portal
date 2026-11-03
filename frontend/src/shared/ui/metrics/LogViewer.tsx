import { useEffect, useMemo, useRef, useState } from 'react';
import { Input, Space, Switch, Tag, Tooltip } from 'antd';
import {
  DownloadOutlined,
  PauseOutlined,
  PlayCircleOutlined,
  SearchOutlined,
} from '@ant-design/icons';

interface Props {
  /** Which ranks are currently subscribed. */
  ranks: number[];
}

type LogLine = {
  ts: string;
  level: 'INFO' | 'WARN' | 'ERROR' | 'DEBUG';
  rank: number;
  msg: string;
};

const LEVELS: LogLine['level'][] = ['INFO', 'INFO', 'INFO', 'INFO', 'WARN', 'INFO', 'INFO'];

const MESSAGES = [
  (_s: number, r: number) => `Initializing DDP process group on rank ${r}`,
  (s: number) => `World size: 16, local rank: ${s % 8}`,
  (s: number) =>
    `Epoch 1 step ${s} loss=${(2.8 * Math.exp(-s / 400) + 0.3).toFixed(4)} lr=${(
      2e-5 *
      Math.min(1, s / 500)
    ).toExponential(2)}`,
  (s: number) => `step=${s}/10000 tokens_per_sec=${(22000 + s * 1.3).toFixed(0)}`,
  (s: number) => `grad_norm=${(1.2 + Math.sin(s / 50) * 0.4).toFixed(3)}`,
  (s: number, r: number) => `[RANK ${r}] all-reduce took ${(20 + (s % 13)).toFixed(0)}ms`,
  (s: number) => `Checkpoint saved to /fsx/ckpts/step-${s}.pt`,
  () => `NCCL_SOCKET_IFNAME=eth0 FI_PROVIDER=efa ready`,
];

const pad = (n: number, w = 2) => String(n).padStart(w, '0');

/** Pre-generate a pool of "real-looking" training log lines. */
const buildLogPool = (): LogLine[] => {
  const lines: LogLine[] = [];
  const start = Date.now() - 30 * 60_000;
  for (let i = 0; i < 200; i += 1) {
    const step = 100 + i * 37;
    const rank = i % 16;
    const d = new Date(start + i * 9_000);
    const ts =
      `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` +
      `.${pad(d.getMilliseconds(), 3)}`;
    const level = LEVELS[i % LEVELS.length];
    const msg = MESSAGES[i % MESSAGES.length](step, rank);
    lines.push({ ts, level, rank, msg });
  }
  // Sprinkle an ERROR line to showcase coloring.
  lines.splice(140, 0, {
    ts: '14:25:47.452',
    level: 'ERROR',
    rank: 3,
    msg: 'NCCL timeout after 600000 ms, aborting. ncclSystemError',
  });
  return lines;
};

const LEVEL_COLORS: Record<LogLine['level'], string> = {
  INFO: '#52c41a',
  WARN: '#faad14',
  ERROR: '#ff4d4f',
  DEBUG: '#8c8c8c',
};

export default function LogViewer({ ranks }: Props) {
  const pool = useMemo(() => buildLogPool(), []);
  const [query, setQuery] = useState('');
  const [tail, setTail] = useState(true);
  const preRef = useRef<HTMLPreElement>(null);

  const filtered = useMemo(() => {
    const rankSet = new Set(ranks);
    return pool.filter((l) => rankSet.has(l.rank));
  }, [pool, ranks]);

  const shown = useMemo(() => {
    if (!query) return filtered;
    const q = query.toLowerCase();
    return filtered.filter((l) => l.msg.toLowerCase().includes(q));
  }, [filtered, query]);

  useEffect(() => {
    if (tail && preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight;
    }
  }, [tail, shown]);

  return (
    <div>
      <Space style={{ marginBottom: 8 }} size="middle" wrap>
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索关键字…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ width: 260 }}
        />
        <Space size={4}>
          <span style={{ fontSize: 12, color: '#666' }}>Tail</span>
          <Switch
            size="small"
            checked={tail}
            onChange={setTail}
            checkedChildren={<PlayCircleOutlined />}
            unCheckedChildren={<PauseOutlined />}
          />
        </Space>
        <Tag color="blue">{shown.length} 行</Tag>
        <Tag color="green">已订阅 RANK: {ranks.join(',') || '-'}</Tag>
        <Tooltip title="下载全部日志">
          <a>
            <DownloadOutlined /> 下载
          </a>
        </Tooltip>
      </Space>

      <pre
        ref={preRef}
        style={{
          background: '#1e1e1e',
          color: '#d4d4d4',
          fontFamily:
            '"SF Mono", Consolas, "Liberation Mono", Menlo, monospace',
          fontSize: 12,
          lineHeight: 1.55,
          padding: 12,
          borderRadius: 6,
          height: 520,
          overflow: 'auto',
          margin: 0,
        }}
      >
        {shown.map((l, idx) => (
          <div key={idx} style={{ whiteSpace: 'pre' }}>
            <span style={{ color: '#858585' }}>{l.ts} </span>
            <span style={{ color: LEVEL_COLORS[l.level], fontWeight: 600 }}>
              [{l.level.padEnd(5)}]
            </span>
            <span style={{ color: '#9cdcfe' }}> [rank-{l.rank}]</span>
            <span> {l.msg}</span>
          </div>
        ))}
        {tail && (
          <div>
            <span style={{ color: '#569cd6' }}>▌</span>
          </div>
        )}
      </pre>
    </div>
  );
}
