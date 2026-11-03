import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Empty,
  Input,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  DownloadOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { fetchInferenceLogs, type LogLine, type LogStream } from '@/api/logs';
import type { InferencePodSummary } from '../api/types';

const { Text } = Typography;

interface Props {
  inferenceId: string;
  pods?: InferencePodSummary[];
  /** 默认主容器名 (= k8s_endpoint_name), 默认筛只看主容器, 排除 nginx/otel sidecar 杂音. */
  mainContainer?: string;
}

const REFRESH_OPTIONS = [
  { label: '5s', value: 5 },
  { label: '15s', value: 15 },
  { label: '暂停', value: 0 },
];

const STREAM_COLORS: Record<LogStream, string> = {
  stdout: 'default',
  stderr: 'volcano',
  agent: 'blue',
};

const lineKey = (l: LogLine) => `${l.timestamp_ms}|${l.stream}|${l.pod ?? ''}|${l.message}`;

// since_ms 游标对 CloudWatch Logs Insights 不可靠 (查询窗口模糊, 同一条 ts 会跨轮重发),
// 故客户端按 (ts+stream+pod+message) 去重: 已显示的不再追加。
function mergeDedup(prev: LogLine[], incoming: LogLine[]): LogLine[] {
  if (incoming.length === 0) return prev;
  const seen = new Set(prev.map(lineKey));
  const fresh = incoming.filter((l) => !seen.has(lineKey(l)));
  if (fresh.length === 0) return prev;
  const merged = [...prev, ...fresh];
  return merged.length > 5000 ? merged.slice(merged.length - 5000) : merged;
}

/**
 * Inference endpoint log viewer · CloudWatch Logs Insights 轮询.
 *
 * 数据来源: HyperPod observability add-on → Fluent Bit DaemonSet →
 * CloudWatch log group, 后端用 inference UUID 字符串 match 检索.
 *
 * 不接 SSE — 推理服务长跑, 看 startup / 报错就够; 真要 follow 走 kubectl.
 */
export default function LogViewer({
  inferenceId,
  pods = [],
  mainContainer,
}: Props) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshSec, setRefreshSec] = useState(15);
  const [keyword, setKeyword] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [warmingUp, setWarmingUp] = useState(false);
  const [podFilter, setPodFilter] = useState<string | undefined>(undefined);
  const [containerFilter, setContainerFilter] = useState<string | undefined>(
    mainContainer,
  );
  const sinceMsRef = useRef<number | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stickyBottomRef = useRef(true);

  const doLoad = useCallback(
    async (mode: 'initial' | 'poll' | 'reload') => {
      if (document.hidden && mode === 'poll') return;
      try {
        const resp = await fetchInferenceLogs(inferenceId, {
          container: containerFilter,
          limit: mode === 'initial' || mode === 'reload' ? 500 : 200,
          sinceMs:
            mode === 'reload' ? undefined : sinceMsRef.current ?? undefined,
        });
        setErr(null);
        setWarmingUp(resp.warming_up);
        if (resp.next_since_ms) sinceMsRef.current = resp.next_since_ms;
        if (mode === 'reload') {
          setLines(resp.lines);
        } else if (resp.lines.length > 0) {
          setLines((prev) => mergeDedup(prev, resp.lines));
        }
      } catch (e) {
        setErr((e as Error).message);
      } finally {
        if (mode === 'initial') setLoading(false);
      }
    },
    [inferenceId, containerFilter],
  );

  useEffect(() => {
    sinceMsRef.current = null;
    setLines([]);
    setLoading(true);
    void doLoad('initial');
  }, [doLoad]);

  useEffect(() => {
    if (refreshSec <= 0) return;
    const t = setInterval(() => void doLoad('poll'), refreshSec * 1000);
    return () => clearInterval(t);
  }, [doLoad, refreshSec]);

  useEffect(() => {
    if (!stickyBottomRef.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines.length]);

  const filtered = useMemo(() => {
    let base = lines;
    if (podFilter) base = base.filter((l) => l.pod === podFilter);
    if (keyword) {
      const kw = keyword.toLowerCase();
      base = base.filter((l) => l.message.toLowerCase().includes(kw));
    }
    return base;
  }, [lines, keyword, podFilter]);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
    stickyBottomRef.current = atBottom;
  }, []);

  const downloadAll = useCallback(() => {
    const text = filtered
      .map(
        (l) =>
          `[${dayjs(l.timestamp_ms).format('YYYY-MM-DD HH:mm:ss')}] ` +
          `[${l.stream}] [${l.pod ?? '-'}] ${l.message}`,
      )
      .join('\n');
    const blob = new Blob([text], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `inference-${inferenceId}-${Date.now()}.log`;
    a.click();
    URL.revokeObjectURL(a.href);
    message.success('日志已下载');
  }, [filtered, inferenceId]);

  return (
    <div>
      <Space wrap style={{ marginBottom: 12 }}>
        <Text strong>容器:</Text>
        <Select
          allowClear
          placeholder="全部容器 (含 nginx/otel sidecar)"
          style={{ width: 240 }}
          value={containerFilter}
          onChange={(v) => {
            setContainerFilter(v);
            // 切容器时清缓存重拉
            sinceMsRef.current = null;
            setLines([]);
            setLoading(true);
          }}
          options={[
            ...(mainContainer
              ? [{ label: `${mainContainer} (主)`, value: mainContainer }]
              : []),
            { label: 'sidecar-reverse-proxy', value: 'sidecar-reverse-proxy' },
            { label: 'otel-collector', value: 'otel-collector' },
          ]}
        />
        <Text strong>Pod:</Text>
        <Select
          allowClear
          placeholder="全部 pod"
          style={{ width: 280 }}
          value={podFilter}
          onChange={setPodFilter}
          options={pods
            .filter((p) => !!p.name)
            .map((p) => ({
              label: `${p.name} · ${p.phase ?? '-'}`,
              value: p.name as string,
            }))}
        />
        <Text strong>关键字:</Text>
        <Input
          allowClear
          placeholder="grep"
          style={{ width: 200 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <Text strong>刷新:</Text>
        <Select
          value={refreshSec}
          onChange={setRefreshSec}
          options={REFRESH_OPTIONS}
          style={{ width: 90 }}
        />
        <Button
          icon={<ReloadOutlined />}
          onClick={() => void doLoad('reload')}
        >
          重载
        </Button>
        <Button
          icon={refreshSec > 0 ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
          onClick={() => setRefreshSec(refreshSec > 0 ? 0 : 15)}
        >
          {refreshSec > 0 ? '暂停' : '继续'}
        </Button>
        <Button icon={<DownloadOutlined />} onClick={downloadAll}>
          下载
        </Button>
      </Space>

      {warmingUp && (
        <Alert
          showIcon
          type="info"
          style={{ marginBottom: 12 }}
          message="日志缓冲期"
          description="Pod 刚启动, Fluent Bit 缓冲未刷出. 等 15s 再刷新即可."
        />
      )}
      {err && (
        <Alert
          showIcon
          type="warning"
          style={{ marginBottom: 12 }}
          message="拉取失败"
          description={err}
          closable
        />
      )}

      <div
        ref={scrollRef}
        onScroll={onScroll}
        style={{
          background: '#0f1419',
          color: '#e6e6e6',
          padding: 12,
          borderRadius: 4,
          height: 520,
          overflow: 'auto',
          fontFamily:
            'Menlo, Monaco, "SF Mono", Consolas, "Liberation Mono", monospace',
          fontSize: 12,
          lineHeight: '18px',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
        }}
      >
        {loading ? (
          <div style={{ textAlign: 'center', paddingTop: 40 }}>
            <Spin />
          </div>
        ) : filtered.length === 0 ? (
          <Empty
            description={
              <span style={{ color: '#888' }}>
                暂无日志. Pod 刚起 / Fluent Bit 还没 flush / 没匹配的关键字.
              </span>
            }
          />
        ) : (
          filtered.map((l, i) => (
            <div key={i} style={{ display: 'flex', gap: 8 }}>
              <span style={{ color: '#666', flexShrink: 0 }}>
                {dayjs(l.timestamp_ms).format('HH:mm:ss.SSS')}
              </span>
              <Tag
                color={STREAM_COLORS[l.stream] || 'default'}
                style={{ marginRight: 0, flexShrink: 0 }}
              >
                {l.stream}
              </Tag>
              <span
                style={{
                  color: '#888',
                  flexShrink: 0,
                  maxWidth: 220,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {l.pod ?? '-'}
              </span>
              <span style={{ flex: 1 }}>{l.message}</span>
            </div>
          ))
        )}
      </div>
      <Text type="secondary" style={{ fontSize: 11 }}>
        共 {filtered.length} 行 (累计 {lines.length}, 上限 5000) · 数据源:
        Fluent Bit → CloudWatch Logs Insights · 字符串 match 推理 ID.
      </Text>
    </div>
  );
}
