import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Empty,
  Input,
  Radio,
  Segmented,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { useTranslation } from 'react-i18next';
import type { RayJobPodSummary } from '../api/types';
import { getRayJobDriverLogs } from '../api/client';
import { useAppStore } from '@/store';
import { withLang } from '@/shared/i18n';

const { Text } = Typography;

interface LogLine {
  ts: number;
  line: string;
  pod: string;
  stream: 'stdout' | 'stderr';
}

interface Props {
  rayjobId: string;
  pods: RayJobPodSummary[];
  /** pod 表"日志"按钮点进来预选。 */
  initialPod?: string;
}

// pod role → 主容器名 (照 cr.py container_name)
function containerOf(pod: RayJobPodSummary | undefined): string {
  return pod?.role === 'worker' ? 'ray-worker' : 'ray-head';
}

function isRunning(pod: RayJobPodSummary | undefined): boolean {
  const v = `${pod?.phase ?? ''}${pod?.status ?? ''}`.toLowerCase();
  return v.includes('running');
}

const lineKey = (l: LogLine) => `${l.ts}|${l.pod}|${l.line}`;

/**
 * RayJob 实时日志 (kubectl logs --follow SSE)。
 * 数据源: k8s.stream_pod_logs (Pod 活时). Pod 死 → 无实时流 (CloudWatch 历史归第二批)。
 */
type LogSource = 'container' | 'driver';

export default function RayJobLogViewer({ rayjobId, pods, initialPod }: Props) {
  const { t } = useTranslation(['rayjob', 'common']);
  const themeMode = useAppStore((s) => s.themeMode);
  // 日志源: container=kubectl logs 容器 stdout (集群/守护) · driver=entrypoint 真输出 (训练)
  const [logSource, setLogSource] = useState<LogSource>('container');
  const [selectedPod, setSelectedPod] = useState<string | undefined>(
    initialPod ?? pods.find((p) => isRunning(p))?.name,
  );
  const [lines, setLines] = useState<LogLine[]>([]);
  const [keyword, setKeyword] = useState('');
  const [sseStatus, setSseStatus] = useState<'idle' | 'connecting' | 'open' | 'error' | 'closed'>(
    'idle',
  );
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stickyBottomRef = useRef(true);

  // driver 日志: 只在 head pod, exec cat 全量 + 轮询 (step 级慢, 免 WS)
  const headPod = useMemo(() => pods.find((p) => p.role === 'head'), [pods]);
  const [driverText, setDriverText] = useState('');
  const [driverLoading, setDriverLoading] = useState(false);
  const [driverErr, setDriverErr] = useState<string | null>(null);
  const [driverRefreshSec, setDriverRefreshSec] = useState(15);

  const podObj = useMemo(() => pods.find((p) => p.name === selectedPod), [pods, selectedPod]);
  const running = isRunning(podObj);

  useEffect(() => {
    if (initialPod) setSelectedPod(initialPod);
  }, [initialPod]);

  const loadDriver = useCallback(async () => {
    if (!headPod?.name) return;
    setDriverLoading(true);
    try {
      const r = await getRayJobDriverLogs(rayjobId, headPod.name);
      setDriverErr(null);
      setDriverText(
        r.found ? r.text : t('logViewer.driverNone'),
      );
    } catch (e) {
      setDriverErr((e as Error).message);
    } finally {
      setDriverLoading(false);
    }
  }, [rayjobId, headPod, t]);

  // driver 轮询 (仅 driver 模式)
  useEffect(() => {
    if (logSource !== 'driver' || !headPod?.name) return;
    void loadDriver();
    if (driverRefreshSec <= 0) return;
    const timer = setInterval(() => void loadDriver(), driverRefreshSec * 1000);
    return () => clearInterval(timer);
  }, [logSource, headPod, driverRefreshSec, loadDriver]);

  useEffect(() => {
    // 仅 container 模式订阅 SSE
    if (logSource !== 'container') {
      setSseStatus('idle');
      return;
    }
    setLines([]);
    if (!selectedPod || !running) {
      setSseStatus('idle');
      return;
    }
    const tok = localStorage.getItem('auth_id_token') || '';
    const url =
      `/api/v1/rayjobs/${encodeURIComponent(rayjobId)}/logs/stream` +
      `?pod=${encodeURIComponent(selectedPod)}` +
      `&container=${encodeURIComponent(containerOf(podObj))}` +
      `&tail_lines=200` +
      (tok ? `&access_token=${encodeURIComponent(tok)}` : '');
    setSseStatus('connecting');
    const es = new EventSource(withLang(url));
    es.onmessage = (ev) => {
      try {
        const p = JSON.parse(ev.data) as
          | { type: 'open' }
          | { type: 'log'; ts: number; line: string; pod: string }
          | { type: 'error'; msg: string }
          | { type: 'close' };
        if (p.type === 'open') {
          setSseStatus('open');
        } else if (p.type === 'log') {
          const nl: LogLine = { ts: p.ts, line: p.line, pod: p.pod, stream: 'stdout' };
          setLines((prev) => {
            const seen = new Set(prev.map(lineKey));
            if (seen.has(lineKey(nl))) return prev;
            const merged = [...prev, nl];
            return merged.length > 5000 ? merged.slice(merged.length - 5000) : merged;
          });
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
  }, [logSource, rayjobId, selectedPod, running, podObj]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickyBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [lines]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickyBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return kw ? lines.filter((l) => l.line.toLowerCase().includes(kw)) : lines;
  }, [lines, keyword]);

  const handleDownload = () => {
    const blob = new Blob(
      [filtered.map((l) => `${dayjs(l.ts).format('HH:mm:ss.SSS')} | ${l.line}`).join('\n')],
      { type: 'text/plain' },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `rayjob-${rayjobId}-${selectedPod ?? 'log'}.log`;
    a.click();
    URL.revokeObjectURL(url);
    message.success(t('logViewer.downloaded', { count: filtered.length }));
  };

  const colors =
    themeMode === 'dark'
      ? { bg: '#1f1f1f', text: '#e8e8e8', ts: '#888' }
      : { bg: '#f6f8fa', text: '#1f1f1f', ts: '#8c8c8c' };

  const sourceSwitch = (
    <Segmented<LogSource>
      value={logSource}
      onChange={setLogSource}
      size="small"
      options={[
        { label: t('logViewer.containerLogs'), value: 'container' },
        { label: t('logViewer.driverLogs'), value: 'driver' },
      ]}
    />
  );

  // ── Driver 日志: entrypoint 真输出 (训练/GPU/task 分发), exec head cat 全量 + 轮询 ──
  if (logSource === 'driver') {
    return (
      <div>
        <Space style={{ marginBottom: 12 }} size="middle" wrap>
          {sourceSwitch}
          {driverLoading && <Tag color="processing">{t('logViewer.driverFetching')}</Tag>}
          {driverErr && <Tag color="red">{t('logViewer.driverFailed')}</Tag>}
          <Space>
            <Text type="secondary" style={{ fontSize: 13 }}>
              {t('common:actions.refresh')}
            </Text>
            <Radio.Group
              value={driverRefreshSec}
              onChange={(e) => setDriverRefreshSec(e.target.value)}
              options={[
                { label: '5s', value: 5 },
                { label: '15s', value: 15 },
                { label: t('logViewer.pause'), value: 0 },
              ]}
              optionType="button"
              buttonStyle="solid"
              size="small"
            />
          </Space>
          <Button size="small" icon={<DownloadOutlined />} onClick={() => void loadDriver()}>
            {t('logViewer.reload')}
          </Button>
        </Space>

        {!headPod && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message={t('logViewer.noHead')}
          />
        )}
        {driverErr && (
          <Alert type="error" showIcon closable style={{ marginBottom: 12 }} message={driverErr} />
        )}

        <div
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
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
            border: themeMode === 'dark' ? '1px solid #303030' : '1px solid #e8e8e8',
          }}
        >
          {driverText || (headPod ? t('logViewer.driverPulling') : '')}
        </div>

        <Space style={{ marginTop: 8, fontSize: 12 }} split={<Text type="secondary">·</Text>}>
          <Text type="secondary">
            {t('logViewer.driverSource')}
          </Text>
          <Text type="secondary">{t('logViewer.driverOutput')}</Text>
        </Space>
      </div>
    );
  }

  // ── 容器日志: kubectl logs 容器 stdout (集群/守护进程) ──
  return (
    <div>
      <Space style={{ marginBottom: 12 }} size="middle" wrap>
        {sourceSwitch}
        {sseStatus === 'open' && <Tag color="green">{t('logViewer.live')}</Tag>}
        {sseStatus === 'connecting' && <Tag color="processing">{t('logViewer.connecting')}</Tag>}
        {sseStatus === 'error' && <Tag color="red">{t('logViewer.sseFailed')}</Tag>}
        <Space>
          <Text type="secondary" style={{ fontSize: 13 }}>
            Pod
          </Text>
          <Select
            value={selectedPod}
            onChange={setSelectedPod}
            placeholder={t('logViewer.podPlaceholder')}
            style={{ width: 340 }}
            size="small"
            options={pods
              .filter((p) => p.name)
              .map((p) => ({
                label: `${p.name}${p.role ? ` (${p.role})` : ''}${isRunning(p) ? '' : t('logViewer.notRunningSuffix')}`,
                value: p.name as string,
              }))}
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
          icon={<DownloadOutlined />}
          onClick={handleDownload}
          disabled={filtered.length === 0}
        >
          {t('common:actions.download')}
        </Button>
      </Space>

      {selectedPod && !running && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message={t('logViewer.podNotRunning')}
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
          border: themeMode === 'dark' ? '1px solid #303030' : '1px solid #e8e8e8',
        }}
      >
        {filtered.length === 0 ? (
          <Empty
            description={keyword ? t('logViewer.noMatch', { keyword }) : t('logViewer.empty')}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            style={{ marginTop: 80 }}
          />
        ) : (
          filtered.map((l, i) => (
            <div key={i} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
              <span style={{ color: colors.ts, marginRight: 8 }}>
                {dayjs(l.ts).format('HH:mm:ss.SSS')}
              </span>
              <span>{l.line}</span>
            </div>
          ))
        )}
      </div>

      <Space style={{ marginTop: 8, fontSize: 12 }} split={<Text type="secondary">·</Text>}>
        <Text type="secondary">{t('logViewer.containerSource')}</Text>
        <Text type="secondary">
          {t('logViewer.shownLines', { count: filtered.length })}
        </Text>
      </Space>
    </div>
  );
}
