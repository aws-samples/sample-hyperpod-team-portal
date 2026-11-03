import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Empty,
  Input,
  Radio,
  Select,
  Spin,
  Tooltip,
  Typography,
  message,
} from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import type { Dayjs } from 'dayjs';
import { buildTimeConstraints } from './logTimeConstraints';
import { AnsiLine } from './ansi';
import type { HistorySource } from './sources';
import { ApiError } from '@/shared/api';
import { useAppStore } from '@/store';
import type { HistoryLogLine, HistoryStreamInfo } from '@/api/logs';

const { Text } = Typography;

interface Props {
  source: HistorySource;
  resourceId: string;
  /** 预选 pod (仅 source.supportsInitialPod 时生效)。 */
  initialPod?: string;
}

/**
 * 完成/报错 task 的历史日志查看器 (CloudWatch)。
 *
 * 两种数据路径 (后端依条件自动选):
 * - 浏览 (无搜索无时间窗): GetLogEvents, 双向翻页 (上滑更早 / 下滑更新)。
 * - 搜索 (有关键字/正则 或 有时间窗): FilterLogEvents, 恒旧→新单向 (仅下滑加载更新)。
 *
 * 每次点「搜索」用当前条件重置窗口; 无限滚动按 next_token 续拉。
 */

type Mode = 'browse' | 'search';

/**
 * 选初始 stream: 有 initialPod 则选该 pod 最后一个 stream (seq 最大, = 最近一次运行/重启)。
 * 优先按完整 pod_name 精确匹配, 回退按末段 (pod_short) 匹配 (老缓存无 pod_name)。
 * 都不中则回退首个 stream。
 */
function pickInitialStream(
  streams: HistoryStreamInfo[],
  supportsInitialPod: boolean,
  initialPod?: string,
): string | undefined {
  if (supportsInitialPod && initialPod) {
    const short = initialPod.split('-').pop();
    const matched = streams
      .filter((s) => s.pod_name === initialPod || s.pod_short === short)
      .sort((a, b) => b.seq - a.seq);
    if (matched.length) return matched[0].stream_name;
  }
  return streams[0]?.stream_name;
}

export default function HistoryLogViewer({
  source,
  resourceId,
  initialPod,
}: Props) {
  const { t } = useTranslation(['logs', 'common']);
  const themeMode = useAppStore((s) => s.themeMode);

  // stream (pod) 列表 + 选中
  const [streams, setStreams] = useState<HistoryStreamInfo[]>([]);
  const [stream, setStream] = useState<string | undefined>();
  const [streamsLoading, setStreamsLoading] = useState(true);
  const [streamsErr, setStreamsErr] = useState<string | null>(null);

  // 搜索条件 (草稿: 输入框实时值, 未提交)
  const [query, setQuery] = useState('');
  const [isRegex, setIsRegex] = useState(false);
  // 开始/结束时间拆成两个独立选择器 (各自可选)
  const [startAt, setStartAt] = useState<Dayjs | null>(null);
  const [endAt, setEndAt] = useState<Dayjs | null>(null);
  // 排序 = 浏览首屏定位端: true=新→旧(定位最新,滚到底), false=旧→新(定位最早,停顶,看开头)。
  // 两种打开后都能上滑看更早/下滑追更新; 只影响初始定位。搜索态锁 false (旧→新)。
  const [sortDesc, setSortDesc] = useState(true);

  // 结果 + 翻页状态
  const [lines, setLines] = useState<HistoryLogLine[]>([]);
  const [mode, setMode] = useState<Mode>('browse');
  const [loading, setLoading] = useState(false);
  // 双向"加载更多"忙标志 (分开, 上/下滑互不阻塞)
  const [loadingUp, setLoadingUp] = useState(false); // 加载更早 (上)
  const [loadingDown, setLoadingDown] = useState(false); // 加载更新 (下)
  const [err, setErr] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  // 有没有更早/更新可加载 (驱动上下加载提示条; 由对应 token 是否存在决定)
  const [hasMoreUp, setHasMoreUp] = useState(false);
  const [hasMoreDown, setHasMoreDown] = useState(false);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  // 双向游标用 ref (同步真相源, 避免 setState 异步导致的旧游标竞态):
  //   fwdRef = 往更新翻 (下滑); bwdRef = 往更早翻 (上滑)。搜索态只用 fwdRef。
  // 窗口恒旧上新下。browse 首屏定位最新 (滚到底), search 定位最早 (停顶)。
  const fwdRef = useRef<string | null>(null);
  const bwdRef = useRef<string | null>(null);
  // 每次搜索自增, 作为"本轮查询"身份; loadMore 只认发起时那一轮 (防跨轮续错游标)。
  const searchIdRef = useRef(0);
  // 已生效的查询条件快照 (产生当前 lines + 游标的那次)。loadMore 用它, 不用草稿输入框。
  const committed = useRef<{
    query?: string;
    isRegex: boolean;
    startMs: number | null;
    endMs: number | null;
    isSearch: boolean;
  }>({ isRegex: false, startMs: null, endMs: null, isSearch: false });

  // ---- 列 streams (进页面 / 换 job) ----
  useEffect(() => {
    let alive = true;
    setStreamsLoading(true);
    source.listStreams(resourceId)
      .then((s) => {
        if (!alive) return;
        setStreams(s);
        setStream(pickInitialStream(s, source.supportsInitialPod, initialPod));
        setStreamsErr(null);
      })
      .catch((e) => alive && setStreamsErr((e as Error).message))
      .finally(() => alive && setStreamsLoading(false));
    return () => {
      alive = false;
    };
  }, [resourceId, initialPod, source]);

  // ---- 执行搜索 / 首屏加载 (重置窗口) ----
  const runSearch = useCallback(async () => {
    if (!stream) return;
    const q = query.trim();
    const startMs = startAt ? startAt.valueOf() : null;
    const endMs = endAt ? endAt.valueOf() : null;
    // 兜底校验: DatePicker 联动禁用已挡住大部分, 但边界(毫秒)仍可能漏, 提交前再拦一次。
    if (startMs != null && endMs != null && startMs >= endMs) {
      message.warning(t('filters.startBeforeEnd'));
      return;
    }
    const isSearch = !!q; // 仅"有搜索词"走 FilterLogEvents (单向旧→新); 否则 browse 双向
    // 同步清游标 + 开新一轮: 之后任何 loadMore 因游标空 / searchId 不符而 bail, 杜绝
    // "新条件配旧游标"竞态 (2026-07-02 409 bug)。
    fwdRef.current = null;
    bwdRef.current = null;
    const myId = ++searchIdRef.current;
    committed.current = { query: q || undefined, isRegex, startMs, endMs, isSearch };
    setLoading(true);
    setLoadingUp(false);
    setLoadingDown(false);
    setHasMoreUp(false);
    setHasMoreDown(false);
    setErr(null);
    setSearched(true);
    // 浏览首屏定位端: 新→旧=最新(滚到底), 旧→新=最早(停顶)。搜索恒旧→新(停顶)。
    const anchor: 'newest' | 'oldest' = sortDesc ? 'newest' : 'oldest';
    try {
      const page = await source.fetchHistory(resourceId, {
        stream,
        query: q || undefined,
        is_regex: isRegex,
        start_ms: startMs,
        end_ms: endMs,
        anchor, // browse 首屏定位端; search 忽略
      });
      if (myId !== searchIdRef.current) return; // 已被新一轮取代, 丢弃
      setLines(page.lines);
      setMode(page.mode);
      if (page.mode === 'search') {
        // 搜索: 单向旧→新, 只有下滑加载更新
        fwdRef.current = page.next_token;
        bwdRef.current = null;
        setHasMoreDown(!!page.next_token);
        setHasMoreUp(false);
      } else {
        // 浏览: 双向 token 都在。定位最新时"更新"侧一般已到头, 但保留提示条,
        // 首次下滑若空且 token 不变会自动收起 (loadDown 的 noMore 判定)。
        fwdRef.current = page.forward_token;
        bwdRef.current = page.backward_token;
        setHasMoreDown(!!page.forward_token);
        setHasMoreUp(!!page.backward_token);
      }
      // 窗口恒旧上新下。定位最新(newest/search-无)→滚到底; 定位最早(oldest/search)→停顶。
      const toTop = page.mode === 'search' || anchor === 'oldest';
      requestAnimationFrame(() => {
        const el = scrollRef.current;
        if (el) el.scrollTop = toTop ? 0 : el.scrollHeight;
      });
    } catch (e) {
      if (myId === searchIdRef.current)
        setErr(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      if (myId === searchIdRef.current) setLoading(false);
    }
  }, [resourceId, source, stream, query, isRegex, startAt, endAt, sortDesc, t]);

  // 选中 stream 后自动跑一次 (浏览态, 空条件)
  useEffect(() => {
    if (stream) void runSearch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream]);

  // ---- 加载更早 (上滑, prepend 到顶, 补偿滚动位置防跳) ----
  const loadUp = useCallback(async () => {
    const tok = bwdRef.current;
    if (!stream || !tok || loadingUp || loading) return;
    const myId = searchIdRef.current;
    const c = committed.current;
    setLoadingUp(true);
    const el = scrollRef.current;
    const prevH = el?.scrollHeight ?? 0;
    const prevTop = el?.scrollTop ?? 0;
    try {
      const page = await source.fetchHistory(resourceId, {
        stream, token: tok, query: c.query, is_regex: c.isRegex,
        start_ms: c.startMs, end_ms: c.endMs, load_dir: 'backward',
      });
      if (myId !== searchIdRef.current) return;
      if (page.lines.length) {
        setLines((cur) => [...page.lines, ...cur]);
        requestAnimationFrame(() => {
          if (el) el.scrollTop = prevTop + (el.scrollHeight - prevH);
        });
      }
      // GetLogEvents 到头时返回相同 token + 空 events; 空且 token 未变 = 已到开头。
      const nb = page.backward_token;
      const noMore = !page.lines.length && nb === tok;
      bwdRef.current = nb; // 保留 token, 供再次上滑重试
      setHasMoreUp(!noMore);
      if (noMore) message.info(t('viewer.reachedStart'));
    } catch (e) {
      bwdRef.current = null;
      setHasMoreUp(false);
      message.error((e as Error).message);
    } finally {
      setLoadingUp(false);
    }
  }, [resourceId, source, stream, loadingUp, loading, t]);

  // ---- 加载更新 (下滑, append 到底) ----
  const loadDown = useCallback(async () => {
    const tok = fwdRef.current;
    if (!stream || !tok || loadingDown || loading) return;
    const myId = searchIdRef.current;
    const c = committed.current;
    setLoadingDown(true);
    try {
      const page = await source.fetchHistory(resourceId, {
        stream, token: tok, query: c.query, is_regex: c.isRegex,
        start_ms: c.startMs, end_ms: c.endMs,
        // search 态续 next_token (无 load_dir); browse 态往更新翻
        ...(c.isSearch ? {} : { load_dir: 'forward' as const }),
      });
      if (myId !== searchIdRef.current) return;
      if (page.lines.length) setLines((cur) => [...cur, ...page.lines]);
      // search: next_token 到头会变 null; browse: forward_token 永不为 null,
      // 到头表现为"空 events + token 不变" → 据此判定已到最新。
      const nf = c.isSearch ? page.next_token : page.forward_token;
      const noMore = c.isSearch
        ? !nf
        : !page.lines.length && nf === tok;
      fwdRef.current = nf;
      setHasMoreDown(!noMore);
      if (noMore) message.info(t('viewer.reachedLatest'));
    } catch (e) {
      fwdRef.current = null;
      setHasMoreDown(false);
      message.error((e as Error).message);
    } finally {
      setLoadingDown(false);
    }
  }, [resourceId, source, stream, loadingDown, loading, t]);

  // ---- 滚动到边缘自动加载: 近顶→更早, 近底→更新 (窗口恒旧上新下) ----
  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (el.scrollTop < 60) void loadUp();
    else if (el.scrollHeight - el.scrollTop - el.clientHeight < 60) void loadDown();
  }, [loadUp, loadDown]);

  const colors =
    themeMode === 'dark'
      ? { bg: '#1f1f1f', text: '#e8e8e8', ts: '#888', stderr: '#ff7a45' }
      : { bg: '#f6f8fa', text: '#1f1f1f', ts: '#8c8c8c', stderr: '#d4380d' };

  if (streamsLoading && streams.length === 0) {
    return <Spin tip={t('viewer.loadingStreams')} style={{ display: 'block', margin: '40px auto' }} />;
  }
  if (streamsErr && streams.length === 0) {
    return (
      <Alert
        type="error"
        showIcon
        message={t('viewer.loadFailed', { error: streamsErr })}
        description={t('viewer.pipelineHint')}
      />
    );
  }
  if (streams.length === 0) {
    return <Empty description={source.emptyHint()} />;
  }

  const streamOptions = streams.map((s) => ({
    value: s.stream_name,
    // 完整 pod 名 + #seq; 老缓存缺 pod_name 回退短名
    label: source.streamTabLabel(s),
  }));


  // 时间选择器联动禁用 (开始≤结束); Pod/任务日志共用同一套逻辑。
  const tc = buildTimeConstraints(startAt, endAt);
  const { disabledStartDate, disabledStartTime, disabledEndDate, disabledEndTime } = tc;

  return (
    <div>
      {/* ===== 查询工具栏 (白底卡片, 与下方日志区视觉区隔; 全宽与日志区对齐) ===== */}
      <Card
        size="small"
        style={{ marginBottom: 12, borderRadius: 12 }}
        styles={{ body: { padding: 16 } }}
      >
        {/* 第一行: Pod | 开始时间 | 结束时间 | 排序(右) */}
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', marginBottom: 12, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 12, color: colors.ts, marginBottom: 4 }}>Pod</div>
            <Select
              style={{ width: 520 }}
              popupMatchSelectWidth={false}
              options={streamOptions}
              value={stream}
              onChange={setStream}
              size="small"
              title={stream}
            />
          </div>
          <div>
            <div style={{ fontSize: 12, color: colors.ts, marginBottom: 4 }}>
              {t('filters.startTime')}{' '}
              <Text type="secondary" style={{ fontSize: 11 }}>
                {t('filters.localTime')}
              </Text>
            </div>
            <DatePicker
              showTime
              size="small"
              placeholder={t('viewer.anyTime')}
              value={startAt}
              onChange={setStartAt}
              disabledDate={disabledStartDate}
              disabledTime={disabledStartTime}
            />
          </div>
          <div>
            <div style={{ fontSize: 12, color: colors.ts, marginBottom: 4 }}>
              {t('filters.endTime')}{' '}
              <Text type="secondary" style={{ fontSize: 11 }}>
                {t('filters.localTime')}
              </Text>
            </div>
            <DatePicker
              showTime
              size="small"
              placeholder={t('viewer.anyTime')}
              value={endAt}
              onChange={setEndAt}
              disabledDate={disabledEndDate}
              disabledTime={disabledEndTime}
            />
          </div>
          {/* 打开定位(首屏定位端): 靠右。有搜索词时锁最早并置灰 (FilterLogEvents 只支持正序)。 */}
          <div style={{ marginLeft: 'auto', whiteSpace: 'nowrap' }}>
            <div style={{ fontSize: 12, color: colors.ts, marginBottom: 4, textAlign: 'left' }}>{t('viewer.openAt')}</div>
            <Tooltip
              title={query.trim() ? t('viewer.openAtSearchTip') : t('viewer.openAtTip')}
            >
              <Radio.Group
                size="small"
                optionType="button"
                buttonStyle="solid"
                disabled={!!query.trim()}
                value={query.trim() || !sortDesc ? 'asc' : 'desc'}
                onChange={(e) => setSortDesc(e.target.value === 'desc')}
              >
                <Radio.Button value="desc">{t('viewer.openAtLatest')}</Radio.Button>
                <Radio.Button value="asc">{t('viewer.openAtEarliest')}</Radio.Button>
              </Radio.Group>
            </Tooltip>
          </div>
        </div>

        {/* 第二行: 匹配模式 | 搜索框(撑满) | 搜索按钮。普通 Input + 独立按钮:
            清空 ✕ 只清文本不发请求, 仅点按钮 / 回车才搜 (allowClear 的 Search 会误触发)。 */}
        <div>
          <div style={{ fontSize: 12, color: colors.ts, marginBottom: 4 }}>
            {t('filters.searchLabel')}{' '}
            <Text type="secondary" style={{ fontSize: 11 }}>
              {isRegex ? t('viewer.searchHintRegex') : t('viewer.searchHintKeyword')}
            </Text>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Radio.Group
              size="small"
              optionType="button"
              buttonStyle="solid"
              value={isRegex ? 'regex' : 'keyword'}
              onChange={(e) => setIsRegex(e.target.value === 'regex')}
            >
              <Radio.Button value="keyword">{t('filters.keyword')}</Radio.Button>
              <Radio.Button value="regex">{t('filters.regex')}</Radio.Button>
            </Radio.Group>
            <Input
              size="small"
              allowClear
              style={{ flex: 1 }}
              placeholder={isRegex ? 'train_loss=\\d+\\.\\d+' : 'train_loss'}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onPressEnter={() => void runSearch()}
            />
            <Button
              type="primary"
              size="small"
              loading={loading}
              onClick={() => void runSearch()}
            >
              {t('common:actions.search')}
            </Button>
          </div>
        </div>
      </Card>

      {/* ===== 状态条 ===== */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 8,
          fontSize: 12,
        }}
      >
        <Text type="secondary">
          {mode === 'search'
            ? t('viewer.status.search', { count: lines.length })
            : t('viewer.status.browse', { count: lines.length })}
        </Text>
        {stream && (
          <Tooltip title={t('viewer.downloadTip')}>
            <Button
              size="small"
              icon={<DownloadOutlined />}
              href={source.downloadUrl(resourceId, stream)}
              target="_blank"
            >
              {t('common:actions.download')}
            </Button>
          </Tooltip>
        )}
      </div>

      {/* ===== 日志区 ===== */}
      <div
        ref={scrollRef}
        onScroll={onScroll}
        style={{
          background: colors.bg,
          color: colors.text,
          fontFamily: '"JetBrains Mono", Menlo, monospace',
          fontSize: 12,
          lineHeight: 1.55,
          height: 520,
          overflow: 'auto',
          padding: '8px 12px',
          borderRadius: 6,
          border: themeMode === 'dark' ? '1px solid #303030' : '1px solid #e8e8e8',
        }}
      >
        {loading ? (
          <Spin tip={t('viewer.querying')} style={{ display: 'block', marginTop: 40 }} />
        ) : err ? (
          <Alert type="error" showIcon message={err} />
        ) : lines.length === 0 && searched ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('filters.noMatch')} />
        ) : (
          <>
            {/* 顶部: 更早 (窗口恒旧上新下) */}
            {hasMoreUp && (
              <div style={{ textAlign: 'center', color: colors.ts, padding: '4px 0' }}>
                {loadingUp ? <Spin size="small" /> : t('viewer.loadEarlier')}
              </div>
            )}
            {lines.map((l, i) => (
              <div key={i} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                <span style={{ color: colors.ts, marginRight: 8 }}>{l.time}</span>
                <span style={{ color: l.stream === 'stderr' ? colors.stderr : colors.text }}>
                  <AnsiLine text={l.log} />
                </span>
              </div>
            ))}
            {/* 底部: 更新 */}
            {hasMoreDown && (
              <div style={{ textAlign: 'center', color: colors.ts, padding: '4px 0' }}>
                {loadingDown ? <Spin size="small" /> : t('viewer.loadNewer')}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
