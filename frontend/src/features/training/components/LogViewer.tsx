import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Empty,
  Input,
  Radio,
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
import { useTranslation } from 'react-i18next';
import { fetchTrainingLogs, type LogLine, type LogStream } from '@/api/logs';
import type { TrainingPodSummary } from '../api/types';
import { useAppStore } from '@/store';
import { withLang } from '@/shared/i18n';

const { Text } = Typography;

interface Props {
  trainingJobId: string;
  /** Container names to offer in the picker. Pass ['trainer'] for HPJ. */
  containerOptions?: string[];
  /** Optional: pods from Detail page — used to populate the pod filter UI. */
  pods?: TrainingPodSummary[];
  /** 打开时预选的 pod (pod 表"日志"按钮点进来), 默认不筛 (全部)。 */
  initialPod?: string;
}

// 存 key 不存译文 (模块级常量), 渲染时再翻译
const REFRESH_OPTIONS = [
  { label: '5s', value: 5 },
  { label: '15s', value: 15 },
  { labelKey: 'logViewer.pause', value: 0 },
] as const;

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
 * xterm-style CloudWatch Logs viewer for a training job.
 *
 * Uses `since_ms` cursor-style polling: each response carries
 * `next_since_ms = lastLine.timestamp_ms + 1`, which we echo on the next
 * poll so new lines append instead of duplicating. Retains lines across
 * polls (bounded to 5000 to keep the DOM snappy).
 */
export default function LogViewer({
  trainingJobId,
  containerOptions = ['trainer'],
  pods = [],
  initialPod,
}: Props) {
  const { t } = useTranslation(['training', 'common']);
  const themeMode = useAppStore((s) => s.themeMode);
  const [lines, setLines] = useState<LogLine[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshSec, setRefreshSec] = useState(15);
  const [container, setContainer] = useState<string | undefined>(
    containerOptions[0],
  );
  const [keyword, setKeyword] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [warmingUp, setWarmingUp] = useState(false);
  const [podFilter, setPodFilter] = useState<string | undefined>(initialPod);
  const sinceMsRef = useRef<number | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stickyBottomRef = useRef(true);

  const doLoad = useCallback(
    async (mode: 'initial' | 'poll' | 'reload') => {
      if (document.hidden && mode === 'poll') return;
      try {
        const resp = await fetchTrainingLogs(trainingJobId, {
          container,
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
    [trainingJobId, container],
  );

  useEffect(() => {
    sinceMsRef.current = null;
    setLines([]);
    setLoading(true);
    void doLoad('initial');
  }, [doLoad]);

  // SSE 实时流: 只在 Pod=Running 时订阅 · 走 Pod stdout 0 延迟
  // Pod 不 Running → 走轮询 CW (下方 useEffect)
  const runningPod = useMemo(() => {
    if (podFilter) {
      return pods.find((p) => p.name === podFilter && p.phase === 'Running');
    }
    return pods.find((p) => p.phase === 'Running');
  }, [pods, podFilter]);

  const [sseStatus, setSseStatus] = useState<
    'idle' | 'connecting' | 'open' | 'error' | 'closed'
  >('idle');

  useEffect(() => {
    if (!runningPod || refreshSec <= 0) {
      setSseStatus('idle');
      return;
    }
    // 修 2 处:
    // 1. URL 之前缺 /v1 段 (vite proxy 不重写, 后端真路径在 /api/v1/...)
    // 2. EventSource 不能设 Authorization header, 后端 middleware 加了
    //    ?access_token= 走 query 验签 (auth_middleware.py 路径 3, 仅 /logs/stream).
    const tok = localStorage.getItem('auth_id_token') || '';
    const url =
      `/api/v1/training-jobs/${encodeURIComponent(trainingJobId)}/logs/stream` +
      `?pod=${encodeURIComponent(runningPod.name)}` +
      `&container=${encodeURIComponent(container || 'trainer')}` +
      `&tail_lines=200` +
      (tok ? `&access_token=${encodeURIComponent(tok)}` : '');
    setSseStatus('connecting');
    const es = new EventSource(withLang(url));
    es.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data) as
          | { type: 'open'; pod: string; ts: number }
          | { type: 'log'; ts: number; line: string; pod: string }
          | { type: 'error'; msg: string }
          | { type: 'close' };
        if (payload.type === 'open') {
          setSseStatus('open');
          return;
        }
        if (payload.type === 'log') {
          const newLine: LogLine = {
            timestamp_ms: payload.ts,
            message: payload.line,
            stream: 'stdout',
            pod: payload.pod,
          };
          setLines((prev) => mergeDedup(prev, [newLine]));
          return;
        }
        if (payload.type === 'error') {
          setErr(payload.msg);
        }
      } catch {
        /* ignore malformed */
      }
    };
    es.onerror = () => {
      setSseStatus('error');
      es.close();
    };
    return () => {
      es.close();
      setSseStatus('closed');
    };
  }, [runningPod, refreshSec, trainingJobId, container]);

  // 轮询: 仅当没 SSE 在跑 (无 running pod 或暂停) 时启动 · 防双源重复行
  useEffect(() => {
    if (refreshSec <= 0) return;
    if (sseStatus === 'open' || sseStatus === 'connecting') return;
    const timer = setInterval(() => void doLoad('poll'), refreshSec * 1000);
    return () => clearInterval(timer);
  }, [refreshSec, doLoad, sseStatus]);

  // Auto-scroll to bottom on new content while user hasn't scrolled up.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickyBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [lines]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight;
    stickyBottomRef.current = distanceFromBottom < 40;
  };

  const filteredLines = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return lines.filter((l) => {
      if (podFilter && l.pod !== podFilter) return false;
      if (kw && !l.message.toLowerCase().includes(kw)) return false;
      return true;
    });
  }, [lines, keyword, podFilter]);

  const handleDownload = () => {
    try {
      const blob = new Blob(
        [
          filteredLines
            .map(
              (l) =>
                `${dayjs(l.timestamp_ms).format('YYYY-MM-DD HH:mm:ss.SSS')} [${l.stream}] ${l.pod ?? '-'} | ${l.message}`,
            )
            .join('\n'),
        ],
        { type: 'text/plain' },
      );
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `training-${trainingJobId}-${Date.now()}.log`;
      a.click();
      URL.revokeObjectURL(url);
      message.success(t('logViewer.downloaded', { count: filteredLines.length }));
    } catch (e) {
      message.error(t('logViewer.downloadFailed', { error: (e as Error).message }));
    }
  };

  const colors =
    themeMode === 'dark'
      ? {
          bg: '#1f1f1f',
          text: '#e8e8e8',
          ts: '#888',
          stderr: '#ff7a45',
          muted: '#999',
        }
      : {
          bg: '#f6f8fa',
          text: '#1f1f1f',
          ts: '#8c8c8c',
          stderr: '#d4380d',
          muted: '#595959',
        };

  const podNames = useMemo(
    () => Array.from(new Set(pods.map((p) => p.name))),
    [pods],
  );

  return (
    <div>
      <Space style={{ marginBottom: 12 }} size="middle" wrap>
        {/* 实时 SSE 连接状态指示 */}
        {sseStatus === 'open' && (
          <Tag color="green" style={{ margin: 0 }}>
            {t('logViewer.live')}
          </Tag>
        )}
        {sseStatus === 'connecting' && (
          <Tag color="processing" style={{ margin: 0 }}>
            {t('logViewer.connecting')}
          </Tag>
        )}
        {sseStatus === 'error' && (
          <Tag color="red" style={{ margin: 0 }}>
            {t('logViewer.sseFailed')}
          </Tag>
        )}
        {sseStatus === 'idle' && !runningPod && pods.length > 0 && (
          <Tag color="default" style={{ margin: 0 }}>
            {t('logViewer.history')}
          </Tag>
        )}
        <Space>
          <Text type="secondary" style={{ fontSize: 13 }}>
            {t('logViewer.container')}
          </Text>
          <Select
            value={container}
            onChange={(v) => setContainer(v)}
            style={{ width: 140 }}
            size="small"
            options={containerOptions.map((c) => ({ label: c, value: c }))}
          />
        </Space>
        {podNames.length > 0 && (
          <Space>
            <Text type="secondary" style={{ fontSize: 13 }}>
              Pod
            </Text>
            <Select
              value={podFilter}
              onChange={setPodFilter}
              allowClear
              placeholder={t('logViewer.podAll')}
              style={{ width: 280 }}
              size="small"
              options={podNames.map((p) => ({ label: p, value: p }))}
            />
          </Space>
        )}
        <Space>
          <Text type="secondary" style={{ fontSize: 13 }}>
            {t('common:actions.refresh')}
          </Text>
          <Radio.Group
            value={refreshSec}
            onChange={(e) => setRefreshSec(e.target.value)}
            options={REFRESH_OPTIONS.map((o) => ({
              label: 'labelKey' in o ? t(o.labelKey) : o.label,
              value: o.value,
            }))}
            optionType="button"
            buttonStyle="solid"
            size="small"
          />
        </Space>
        <Input.Search
          placeholder={t('logViewer.keywordPlaceholder')}
          allowClear
          onChange={(e) => setKeyword(e.target.value)}
          style={{ width: 240 }}
          size="small"
        />
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={() => void doLoad('reload')}
        >
          {t('logViewer.reload')}
        </Button>
        <Button
          size="small"
          icon={<DownloadOutlined />}
          onClick={handleDownload}
          disabled={filteredLines.length === 0}
        >
          {t('common:actions.download')}
        </Button>
      </Space>

      {err && (
        <Alert
          type="error"
          showIcon
          closable
          style={{ marginBottom: 12 }}
          message={t('logViewer.loadFailed', { error: err })}
          description={t('logViewer.pipelineDesc')}
        />
      )}

      {warmingUp && !err && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          icon={<Spin size="small" />}
          message={t('logViewer.warmingUp')}
        />
      )}

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        style={{
          background: colors.bg,
          color: colors.text,
          fontFamily: '"JetBrains Mono", "Fira Code", Menlo, monospace',
          fontSize: 12,
          lineHeight: 1.55,
          height: 520,
          overflow: 'auto',
          padding: '8px 12px',
          borderRadius: 6,
          border:
            themeMode === 'dark' ? '1px solid #303030' : '1px solid #e8e8e8',
        }}
      >
        {loading && lines.length === 0 ? (
          <div
            style={{
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Spin tip={t('logViewer.fetching')} />
          </div>
        ) : filteredLines.length === 0 ? (
          <Empty
            description={
              keyword
                ? t('logViewer.noMatch', { keyword })
                : t('logViewer.empty')
            }
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            style={{ marginTop: 80 }}
          />
        ) : (
          filteredLines.map((l, i) => (
            <div key={i} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
              <span style={{ color: colors.ts, marginRight: 8 }}>
                {dayjs(l.timestamp_ms).format('HH:mm:ss.SSS')}
              </span>
              <Tag
                color={STREAM_COLORS[l.stream] ?? 'default'}
                style={{ fontSize: 10, lineHeight: '14px', padding: '0 4px', marginRight: 6 }}
              >
                {l.stream}
              </Tag>
              {l.pod && (
                <span style={{ color: colors.muted, marginRight: 6, fontSize: 11 }}>
                  {l.pod.slice(-20)}
                </span>
              )}
              <span style={{ color: l.stream === 'stderr' ? colors.stderr : colors.text }}>
                {l.message}
              </span>
            </div>
          ))
        )}
      </div>

      <Space
        style={{ marginTop: 8, fontSize: 12 }}
        split={<Text type="secondary">·</Text>}
      >
        <Text type="secondary">
          {t('logViewer.source')}
        </Text>
        <Text type="secondary">
          {t('logViewer.shownLines', { shown: filteredLines.length, count: lines.length })}
        </Text>
        {refreshSec > 0 ? (
          <Text type="secondary">
            <PlayCircleOutlined /> {t('logViewer.autoRefresh', { sec: refreshSec })}
          </Text>
        ) : (
          <Text type="secondary">
            <PauseCircleOutlined /> {t('logViewer.paused')}
          </Text>
        )}
      </Space>
    </div>
  );
}
