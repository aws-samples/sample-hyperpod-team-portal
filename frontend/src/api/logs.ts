/**
 * Log tail API — wraps the CloudWatch Logs Insights proxy.
 * Backend: services/platform-api/app/modules/logs/router.py
 *
 * @deprecated Wave 5 P0-4 — 暂保留 (logs feature 尚未拆出),
 * 建立 features/logs/api/ 后请把内容迁过去并删本文件.
 */
import { apiFetch } from '@/shared/api';
import { currentLocale } from '@/shared/i18n';

export type LogStream = 'stdout' | 'stderr' | 'agent';

export interface LogLine {
  timestamp_ms: number;
  message: string;
  stream: LogStream;
  pod?: string | null;
  container?: string | null;
  node?: string | null;
}

export interface LogResponse {
  lines: LogLine[];
  next_since_ms: number | null;
  warming_up: boolean;
  source: 'cloudwatch' | 'pod_exec' | 'none';
}

export function fetchTrainingLogs(
  id: string,
  params?: { container?: string; limit?: number; sinceMs?: number },
): Promise<LogResponse> {
  const qs = new URLSearchParams();
  if (params?.container) qs.set('container', params.container);
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  if (params?.sinceMs !== undefined) qs.set('since_ms', String(params.sinceMs));
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<LogResponse>(
    `/training-jobs/${encodeURIComponent(id)}/logs${suffix}`,
  );
}

export function fetchInferenceLogs(
  id: string,
  params?: { container?: string; limit?: number; sinceMs?: number },
): Promise<LogResponse> {
  const qs = new URLSearchParams();
  if (params?.container) qs.set('container', params.container);
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  if (params?.sinceMs !== undefined) qs.set('since_ms', String(params.sinceMs));
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<LogResponse>(
    `/inferences/${encodeURIComponent(id)}/logs${suffix}`,
  );
}

// ===== 历史日志 (完成/报错 task · CloudWatch get_log_events) =====

export interface HistoryStreamInfo {
  stream_name: string;
  pod_name: string; // 完整 pod 名 (下拉显示); 老缓存可能为空串
  pod_short: string;
  seq: number;
  first_ts: number;
  last_ts: number;
}

export interface HistoryLogLine {
  time: string;
  stream: 'stdout' | 'stderr';
  log: string;
}

export interface HistoryLogPage {
  lines: HistoryLogLine[];
  // search 态单向游标 (旧→新)
  next_token: string | null;
  // browse 态双向游标: forward=往更新(下滑), backward=往更早(上滑)
  forward_token: string | null;
  backward_token: string | null;
  // "browse" = GetLogEvents 同屏双向; "search" = FilterLogEvents 单向 (旧→新)。
  mode: 'browse' | 'search';
}

/** 历史日志翻页/搜索参数。有搜索词=search(单向); 否则 browse(同屏双向)。 */
export interface HistoryQuery {
  stream: string;
  token?: string | null;
  query?: string;
  is_regex?: boolean;
  start_ms?: number | null;
  end_ms?: number | null;
  // 浏览态翻页方向: 空=首屏(定位,返双向token); forward=下滑追更新; backward=上滑看更早。
  load_dir?: 'forward' | 'backward';
  // 浏览首屏定位端: newest=最新(新→旧); oldest=最早(旧→新)。搜索态忽略。
  anchor?: 'newest' | 'oldest';
}

export function fetchTrainingLogStreams(
  id: string,
): Promise<HistoryStreamInfo[]> {
  return apiFetch<HistoryStreamInfo[]>(
    `/training-jobs/${encodeURIComponent(id)}/log-streams`,
  );
}

export function fetchTrainingLogHistory(
  id: string,
  params: HistoryQuery,
): Promise<HistoryLogPage> {
  const qs = new URLSearchParams();
  qs.set('stream', params.stream);
  if (params.token) qs.set('token', params.token);
  if (params.query) qs.set('query', params.query);
  if (params.is_regex) qs.set('is_regex', 'true');
  if (params.start_ms != null) qs.set('start_ms', String(params.start_ms));
  if (params.end_ms != null) qs.set('end_ms', String(params.end_ms));
  if (params.load_dir) qs.set('load_dir', params.load_dir);
  if (params.anchor) qs.set('anchor', params.anchor);
  return apiFetch<HistoryLogPage>(
    `/training-jobs/${encodeURIComponent(id)}/logs/history?${qs.toString()}`,
  );
}

// ===== 整任务搜索 (跨所有 pod · Logs Insights) =====

export interface WholeTaskLogLine {
  time: string;
  stream: 'stdout' | 'stderr';
  log: string;
  pod: string; // 来源 pod 名 (跨 pod 混排, 标出自哪个 pod)
}

export interface WholeTaskSearchResult {
  lines: WholeTaskLogLine[];
  truncated: boolean; // 命中达上限 (1万) 被截断 → 提示缩小时间窗/加关键字
}

/** 整任务搜索: 跨该任务所有 pod。query 空=全部; 异步 (后端 Insights, 秒级)。 */
export function searchWholeTaskLogs(
  id: string,
  params: {
    query?: string;
    is_regex?: boolean;
    start_ms?: number | null;
    end_ms?: number | null;
  },
): Promise<WholeTaskSearchResult> {
  const qs = new URLSearchParams();
  if (params.query) qs.set('query', params.query);
  if (params.is_regex) qs.set('is_regex', 'true');
  if (params.start_ms != null) qs.set('start_ms', String(params.start_ms));
  if (params.end_ms != null) qs.set('end_ms', String(params.end_ms));
  return apiFetch<WholeTaskSearchResult>(
    `/training-jobs/${encodeURIComponent(id)}/logs/search-all?${qs.toString()}`,
  );
}

/** 下载 URL (浏览器直接打开触发下载, 带 auth token query)。 */
export function trainingLogHistoryDownloadUrl(
  id: string,
  stream: string,
): string {
  const tok = localStorage.getItem('auth_id_token') || '';
  const qs = new URLSearchParams();
  qs.set('stream', stream);
  if (tok) qs.set('access_token', tok);
  qs.set('lang', currentLocale());
  return `/api/v1/training-jobs/${encodeURIComponent(id)}/logs/history/download?${qs.toString()}`;
}

// ===== 推理历史日志 (停止/终态 · CloudWatch, 多 pod tab) =====

export function fetchInferenceLogStreams(
  id: string,
): Promise<HistoryStreamInfo[]> {
  return apiFetch<HistoryStreamInfo[]>(
    `/inferences/${encodeURIComponent(id)}/log-streams`,
  );
}

export function fetchInferenceLogHistory(
  id: string,
  params: HistoryQuery,
): Promise<HistoryLogPage> {
  const qs = new URLSearchParams();
  qs.set('stream', params.stream);
  if (params.token) qs.set('token', params.token);
  if (params.query) qs.set('query', params.query);
  if (params.is_regex) qs.set('is_regex', 'true');
  if (params.start_ms != null) qs.set('start_ms', String(params.start_ms));
  if (params.end_ms != null) qs.set('end_ms', String(params.end_ms));
  if (params.load_dir) qs.set('load_dir', params.load_dir);
  if (params.anchor) qs.set('anchor', params.anchor);
  return apiFetch<HistoryLogPage>(
    `/inferences/${encodeURIComponent(id)}/logs/history?${qs.toString()}`,
  );
}

export function inferenceLogHistoryDownloadUrl(
  id: string,
  stream: string,
): string {
  const tok = localStorage.getItem('auth_id_token') || '';
  const qs = new URLSearchParams();
  qs.set('stream', stream);
  if (tok) qs.set('access_token', tok);
  qs.set('lang', currentLocale());
  return `/api/v1/inferences/${encodeURIComponent(id)}/logs/history/download?${qs.toString()}`;
}

/** 推理整任务搜索: 跨该 endpoint 所有 pod。query 空=全部。 */
export function searchWholeInferenceLogs(
  id: string,
  params: {
    query?: string;
    is_regex?: boolean;
    start_ms?: number | null;
    end_ms?: number | null;
  },
): Promise<WholeTaskSearchResult> {
  const qs = new URLSearchParams();
  if (params.query) qs.set('query', params.query);
  if (params.is_regex) qs.set('is_regex', 'true');
  if (params.start_ms != null) qs.set('start_ms', String(params.start_ms));
  if (params.end_ms != null) qs.set('end_ms', String(params.end_ms));
  return apiFetch<WholeTaskSearchResult>(
    `/inferences/${encodeURIComponent(id)}/logs/search-all?${qs.toString()}`,
  );
}

// ===== Dynamo 多机推理历史日志 (停止/终态 · CloudWatch, 跨 frontend + worker pod tab) =====

export function fetchDynamoLogStreams(
  id: string,
): Promise<HistoryStreamInfo[]> {
  return apiFetch<HistoryStreamInfo[]>(
    `/dynamo-inferences/${encodeURIComponent(id)}/log-streams`,
  );
}

export function fetchDynamoLogHistory(
  id: string,
  params: HistoryQuery,
): Promise<HistoryLogPage> {
  const qs = new URLSearchParams();
  qs.set('stream', params.stream);
  if (params.token) qs.set('token', params.token);
  if (params.query) qs.set('query', params.query);
  if (params.is_regex) qs.set('is_regex', 'true');
  if (params.start_ms != null) qs.set('start_ms', String(params.start_ms));
  if (params.end_ms != null) qs.set('end_ms', String(params.end_ms));
  if (params.load_dir) qs.set('load_dir', params.load_dir);
  if (params.anchor) qs.set('anchor', params.anchor);
  return apiFetch<HistoryLogPage>(
    `/dynamo-inferences/${encodeURIComponent(id)}/logs/history?${qs.toString()}`,
  );
}

export function dynamoLogHistoryDownloadUrl(
  id: string,
  stream: string,
): string {
  const tok = localStorage.getItem('auth_id_token') || '';
  const qs = new URLSearchParams();
  qs.set('stream', stream);
  if (tok) qs.set('access_token', tok);
  qs.set('lang', currentLocale());
  return `/api/v1/dynamo-inferences/${encodeURIComponent(id)}/logs/history/download?${qs.toString()}`;
}

/** Dynamo 整任务搜索: 跨该多机推理所有 pod (frontend + worker)。query 空=全部。 */
export function searchWholeDynamoLogs(
  id: string,
  params: {
    query?: string;
    is_regex?: boolean;
    start_ms?: number | null;
    end_ms?: number | null;
  },
): Promise<WholeTaskSearchResult> {
  const qs = new URLSearchParams();
  if (params.query) qs.set('query', params.query);
  if (params.is_regex) qs.set('is_regex', 'true');
  if (params.start_ms != null) qs.set('start_ms', String(params.start_ms));
  if (params.end_ms != null) qs.set('end_ms', String(params.end_ms));
  return apiFetch<WholeTaskSearchResult>(
    `/dynamo-inferences/${encodeURIComponent(id)}/logs/search-all?${qs.toString()}`,
  );
}

// ===== Rayjob 历史日志 (停止/终态 · CloudWatch, 跨 head + worker pod tab) =====

export function fetchRayjobLogStreams(
  id: string,
): Promise<HistoryStreamInfo[]> {
  return apiFetch<HistoryStreamInfo[]>(
    `/rayjobs/${encodeURIComponent(id)}/log-streams`,
  );
}

export function fetchRayjobLogHistory(
  id: string,
  params: HistoryQuery,
): Promise<HistoryLogPage> {
  const qs = new URLSearchParams();
  qs.set('stream', params.stream);
  if (params.token) qs.set('token', params.token);
  if (params.query) qs.set('query', params.query);
  if (params.is_regex) qs.set('is_regex', 'true');
  if (params.start_ms != null) qs.set('start_ms', String(params.start_ms));
  if (params.end_ms != null) qs.set('end_ms', String(params.end_ms));
  if (params.load_dir) qs.set('load_dir', params.load_dir);
  if (params.anchor) qs.set('anchor', params.anchor);
  return apiFetch<HistoryLogPage>(
    `/rayjobs/${encodeURIComponent(id)}/logs/history?${qs.toString()}`,
  );
}

export function rayjobLogHistoryDownloadUrl(
  id: string,
  stream: string,
): string {
  const tok = localStorage.getItem('auth_id_token') || '';
  const qs = new URLSearchParams();
  qs.set('stream', stream);
  if (tok) qs.set('access_token', tok);
  qs.set('lang', currentLocale());
  return `/api/v1/rayjobs/${encodeURIComponent(id)}/logs/history/download?${qs.toString()}`;
}

/** Rayjob 整任务搜索: 跨该 Ray 任务所有 pod (head + worker)。query 空=全部。 */
export function searchWholeRayjobLogs(
  id: string,
  params: {
    query?: string;
    is_regex?: boolean;
    start_ms?: number | null;
    end_ms?: number | null;
  },
): Promise<WholeTaskSearchResult> {
  const qs = new URLSearchParams();
  if (params.query) qs.set('query', params.query);
  if (params.is_regex) qs.set('is_regex', 'true');
  if (params.start_ms != null) qs.set('start_ms', String(params.start_ms));
  if (params.end_ms != null) qs.set('end_ms', String(params.end_ms));
  return apiFetch<WholeTaskSearchResult>(
    `/rayjobs/${encodeURIComponent(id)}/logs/search-all?${qs.toString()}`,
  );
}

// ===== llm-d 多机推理历史日志 (停止/终态 · CloudWatch, 跨 LWS worker + gateway pod tab) =====

export function fetchLlmdLogStreams(
  id: string,
): Promise<HistoryStreamInfo[]> {
  return apiFetch<HistoryStreamInfo[]>(
    `/llmd/${encodeURIComponent(id)}/log-streams`,
  );
}

export function fetchLlmdLogHistory(
  id: string,
  params: HistoryQuery,
): Promise<HistoryLogPage> {
  const qs = new URLSearchParams();
  qs.set('stream', params.stream);
  if (params.token) qs.set('token', params.token);
  if (params.query) qs.set('query', params.query);
  if (params.is_regex) qs.set('is_regex', 'true');
  if (params.start_ms != null) qs.set('start_ms', String(params.start_ms));
  if (params.end_ms != null) qs.set('end_ms', String(params.end_ms));
  if (params.load_dir) qs.set('load_dir', params.load_dir);
  if (params.anchor) qs.set('anchor', params.anchor);
  return apiFetch<HistoryLogPage>(
    `/llmd/${encodeURIComponent(id)}/logs/history?${qs.toString()}`,
  );
}

export function llmdLogHistoryDownloadUrl(
  id: string,
  stream: string,
): string {
  const tok = localStorage.getItem('auth_id_token') || '';
  const qs = new URLSearchParams();
  qs.set('stream', stream);
  if (tok) qs.set('access_token', tok);
  qs.set('lang', currentLocale());
  return `/api/v1/llmd/${encodeURIComponent(id)}/logs/history/download?${qs.toString()}`;
}

/** llm-d 整任务搜索: 跨该多机推理所有 pod (LWS worker + gateway)。query 空=全部。 */
export function searchWholeLlmdLogs(
  id: string,
  params: {
    query?: string;
    is_regex?: boolean;
    start_ms?: number | null;
    end_ms?: number | null;
  },
): Promise<WholeTaskSearchResult> {
  const qs = new URLSearchParams();
  if (params.query) qs.set('query', params.query);
  if (params.is_regex) qs.set('is_regex', 'true');
  if (params.start_ms != null) qs.set('start_ms', String(params.start_ms));
  if (params.end_ms != null) qs.set('end_ms', String(params.end_ms));
  return apiFetch<WholeTaskSearchResult>(
    `/llmd/${encodeURIComponent(id)}/logs/search-all?${qs.toString()}`,
  );
}

// ===== 开发机历史日志 (停止/终态 · CloudWatch, workspace + direct-ssh-init 双容器) =====

export function fetchDevInstanceLogStreams(
  id: string,
): Promise<HistoryStreamInfo[]> {
  return apiFetch<HistoryStreamInfo[]>(
    `/dev-instances/${encodeURIComponent(id)}/log-streams`,
  );
}

export function fetchDevInstanceLogHistory(
  id: string,
  params: HistoryQuery,
): Promise<HistoryLogPage> {
  const qs = new URLSearchParams();
  qs.set('stream', params.stream);
  if (params.token) qs.set('token', params.token);
  if (params.query) qs.set('query', params.query);
  if (params.is_regex) qs.set('is_regex', 'true');
  if (params.start_ms != null) qs.set('start_ms', String(params.start_ms));
  if (params.end_ms != null) qs.set('end_ms', String(params.end_ms));
  if (params.load_dir) qs.set('load_dir', params.load_dir);
  if (params.anchor) qs.set('anchor', params.anchor);
  return apiFetch<HistoryLogPage>(
    `/dev-instances/${encodeURIComponent(id)}/logs/history?${qs.toString()}`,
  );
}

export function devInstanceLogHistoryDownloadUrl(
  id: string,
  stream: string,
): string {
  const tok = localStorage.getItem('auth_id_token') || '';
  const qs = new URLSearchParams();
  qs.set('stream', stream);
  if (tok) qs.set('access_token', tok);
  qs.set('lang', currentLocale());
  return `/api/v1/dev-instances/${encodeURIComponent(id)}/logs/history/download?${qs.toString()}`;
}

/** 开发机整任务搜索: 跨该开发机所有 pod。query 空=全部。 */
export function searchWholeDevInstanceLogs(
  id: string,
  params: {
    query?: string;
    is_regex?: boolean;
    start_ms?: number | null;
    end_ms?: number | null;
  },
): Promise<WholeTaskSearchResult> {
  const qs = new URLSearchParams();
  if (params.query) qs.set('query', params.query);
  if (params.is_regex) qs.set('is_regex', 'true');
  if (params.start_ms != null) qs.set('start_ms', String(params.start_ms));
  if (params.end_ms != null) qs.set('end_ms', String(params.end_ms));
  return apiFetch<WholeTaskSearchResult>(
    `/dev-instances/${encodeURIComponent(id)}/logs/search-all?${qs.toString()}`,
  );
}
