import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Empty,
  Input,
  Radio,
  Spin,
  Typography,
  message,
} from 'antd';
import type { Dayjs } from 'dayjs';
import type { WholeTaskLogLine } from '@/api/logs';
import { AnsiLine } from './ansi';
import { buildTimeConstraints } from './logTimeConstraints';
import type { HistorySource } from './sources';
import { ApiError } from '@/shared/api';
import { useAppStore } from '@/store';

const { Text } = Typography;

interface Props {
  source: HistorySource;
  resourceId: string;
}

/**
 * 整任务 (跨所有 pod) 日志搜索。走后端 Logs Insights (异步, 秒级)。
 * 一次性返回 (无翻页); 命中达上限 (1万) 提示缩小范围。每行标来源 pod。
 * 与单 Pod 组件分离: 状态独立, 语义清晰 (无双向翻页/游标)。
 */
export default function WholeTaskSearch({ source, resourceId }: Props) {
  const { t } = useTranslation(['logs', 'common']);
  const themeMode = useAppStore((s) => s.themeMode);
  const [query, setQuery] = useState('');
  const [isRegex, setIsRegex] = useState(false);
  const [startAt, setStartAt] = useState<Dayjs | null>(null);
  const [endAt, setEndAt] = useState<Dayjs | null>(null);

  const [lines, setLines] = useState<WholeTaskLogLine[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const runSearch = useCallback(async () => {
    if (!source.searchAll) return;
    const startMs = startAt ? startAt.valueOf() : null;
    const endMs = endAt ? endAt.valueOf() : null;
    if (startMs != null && endMs != null && startMs >= endMs) {
      message.warning(t('filters.startBeforeEnd'));
      return;
    }
    setLoading(true);
    setErr(null);
    setSearched(true);
    try {
      const res = await source.searchAll(resourceId, {
        query: query.trim() || undefined,
        is_regex: isRegex,
        start_ms: startMs,
        end_ms: endMs,
      });
      setLines(res.lines);
      setTruncated(res.truncated);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : (e as Error).message);
      setLines([]);
    } finally {
      setLoading(false);
    }
  }, [source, resourceId, query, isRegex, startAt, endAt, t]);

  const colors =
    themeMode === 'dark'
      ? { ts: '#888', text: '#e8e8e8', bg: '#1f1f1f', stderr: '#ff7a45', podtag: '#17293f', podtagT: '#69b1ff' }
      : { ts: '#8c8c8c', text: '#1f1f1f', bg: '#f6f8fa', stderr: '#d4380d', podtag: '#e6f0ff', podtagT: '#0958d9' };

  const tc = buildTimeConstraints(startAt, endAt);

  return (
    <div>
      {/* 查询工具栏 (白底卡片, 全宽与下方结果区对齐) */}
      <Card
        size="small"
        style={{ marginBottom: 12, borderRadius: 12 }}
        styles={{ body: { padding: 16 } }}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message={source.wholeSearchBanner()}
        />
        {/* 时间窗 */}
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', marginBottom: 12, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 12, color: colors.ts, marginBottom: 4 }}>
              {t('filters.startTime')}{' '}
              <Text type="secondary" style={{ fontSize: 11 }}>{t('filters.localTime')}</Text>
            </div>
            <DatePicker
              showTime
              size="small"
              placeholder={t('wholeSearch.startPlaceholder')}
              value={startAt}
              onChange={setStartAt}
              disabledDate={tc.disabledStartDate}
              disabledTime={tc.disabledStartTime}
            />
          </div>
          <div>
            <div style={{ fontSize: 12, color: colors.ts, marginBottom: 4 }}>
              {t('filters.endTime')}{' '}
              <Text type="secondary" style={{ fontSize: 11 }}>{t('filters.localTime')}</Text>
            </div>
            <DatePicker
              showTime
              size="small"
              placeholder={t('wholeSearch.endPlaceholder')}
              value={endAt}
              onChange={setEndAt}
              disabledDate={tc.disabledEndDate}
              disabledTime={tc.disabledEndTime}
            />
          </div>
        </div>
        {/* 匹配模式 + 搜索框(全宽) + 搜索 */}
        <div>
          <div style={{ fontSize: 12, color: colors.ts, marginBottom: 4 }}>
            {t('filters.searchLabel')}{' '}
            <Text type="secondary" style={{ fontSize: 11 }}>
              {isRegex ? t('wholeSearch.hintRegex') : t('wholeSearch.hintKeyword')}
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
            <Button type="primary" size="small" loading={loading} onClick={() => void runSearch()}>
              {t('common:actions.search')}
            </Button>
          </div>
        </div>
      </Card>

      {truncated && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 8 }}
          message={t('wholeSearch.truncated')}
        />
      )}
      <div style={{ fontSize: 12, color: colors.ts, marginBottom: 8 }}>
        {searched ? t('wholeSearch.matched', { count: lines.length }) : t('wholeSearch.setConditions')}
      </div>

      {/* 日志区 */}
      <div
        style={{
          background: colors.bg,
          color: colors.text,
          fontFamily: '"JetBrains Mono", Menlo, monospace',
          fontSize: 12,
          lineHeight: 1.6,
          height: 520,
          overflow: 'auto',
          padding: '8px 12px',
          borderRadius: 6,
          border: themeMode === 'dark' ? '1px solid #303030' : '1px solid #e8e8e8',
        }}
      >
        {loading ? (
          <Spin tip={t('wholeSearch.querying')} style={{ display: 'block', marginTop: 40 }} />
        ) : err ? (
          <Alert type="error" showIcon message={err} />
        ) : lines.length === 0 && searched ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('filters.noMatch')} />
        ) : (
          lines.map((l, i) => (
            <div key={i} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
              <span style={{ color: colors.ts, marginRight: 8 }}>{l.time}</span>
              {l.pod && (
                <span
                  style={{
                    fontSize: 10,
                    padding: '0 6px',
                    borderRadius: 4,
                    background: colors.podtag,
                    color: colors.podtagT,
                    marginRight: 6,
                  }}
                >
                  {l.pod}
                </span>
              )}
              <span style={{ color: l.stream === 'stderr' ? colors.stderr : colors.text }}>
                <AnsiLine text={l.log} />
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
