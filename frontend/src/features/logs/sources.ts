/**
 * HistorySource: 各任务类型的历史日志差异描述对象。
 * 公用 HistoryLogViewer / WholeTaskSearch 消费它, 任务类型差异全收敛于此。
 * 新增 Dynamo/Ray 时只加一个 source 对象, 组件本体不动。
 */
import {
  dynamoLogHistoryDownloadUrl,
  fetchDynamoLogHistory,
  fetchDynamoLogStreams,
  fetchInferenceLogHistory,
  fetchInferenceLogStreams,
  fetchLlmdLogHistory,
  fetchLlmdLogStreams,
  fetchTrainingLogHistory,
  fetchTrainingLogStreams,
  inferenceLogHistoryDownloadUrl,
  llmdLogHistoryDownloadUrl,
  rayjobLogHistoryDownloadUrl,
  fetchRayjobLogHistory,
  fetchRayjobLogStreams,
  searchWholeDynamoLogs,
  searchWholeInferenceLogs,
  searchWholeLlmdLogs,
  devInstanceLogHistoryDownloadUrl,
  fetchDevInstanceLogHistory,
  fetchDevInstanceLogStreams,
  searchWholeDevInstanceLogs,
  searchWholeRayjobLogs,
  searchWholeTaskLogs,
  trainingLogHistoryDownloadUrl,
  type HistoryLogPage,
  type HistoryQuery,
  type HistoryStreamInfo,
  type WholeTaskSearchResult,
} from '@/api/logs';
import i18n from '@/shared/i18n';

export interface HistorySource {
  listStreams: (id: string) => Promise<HistoryStreamInfo[]>;
  fetchHistory: (id: string, params: HistoryQuery) => Promise<HistoryLogPage>;
  /** 无 = 不渲染整任务搜索分段。 */
  searchAll?: (
    id: string,
    params: {
      query?: string;
      is_regex?: boolean;
      start_ms?: number | null;
      end_ms?: number | null;
    },
  ) => Promise<WholeTaskSearchResult>;
  downloadUrl: (id: string, stream: string) => string;
  /** 训练支持从实时抽屉跳来预选 pod; 其他类型可不支持。 */
  supportsInitialPod: boolean;
  /** stream 列表为空时的提示文案 (调用时才翻译, 不在模块加载时求值)。 */
  emptyHint: () => string;
  /** 整任务搜索区顶部说明 banner 文案 (训练=任务, 推理=endpoint; 调用时才翻译)。 */
  wholeSearchBanner: () => string;
  /** stream tab / 下拉的显示名。 */
  streamTabLabel: (s: HistoryStreamInfo) => string;
}

export const trainingSource: HistorySource = {
  listStreams: fetchTrainingLogStreams,
  fetchHistory: fetchTrainingLogHistory,
  searchAll: searchWholeTaskLogs,
  downloadUrl: trainingLogHistoryDownloadUrl,
  supportsInitialPod: true,
  emptyHint: () => i18n.t('sources.training.empty', { ns: 'logs' }),
  wholeSearchBanner: () => i18n.t('sources.training.banner', { ns: 'logs' }),
  // 训练: 完整 pod 名 + #seq (老缓存缺 pod_name 回退短名)
  streamTabLabel: (s) => `${s.pod_name || s.pod_short}-#${s.seq}`,
};

export const inferenceSource: HistorySource = {
  listStreams: fetchInferenceLogStreams,
  fetchHistory: fetchInferenceLogHistory,
  searchAll: searchWholeInferenceLogs,
  downloadUrl: inferenceLogHistoryDownloadUrl,
  supportsInitialPod: false,
  emptyHint: () => i18n.t('sources.inference.empty', { ns: 'logs' }),
  wholeSearchBanner: () => i18n.t('sources.inference.banner', { ns: 'logs' }),
  // 完整 pod 名 + #seq (老缓存缺 pod_name 回退短名), 与训练一致
  streamTabLabel: (s) => `${s.pod_name || s.pod_short}-#${s.seq}`,
};

export const dynamoSource: HistorySource = {
  listStreams: fetchDynamoLogStreams,
  fetchHistory: fetchDynamoLogHistory,
  searchAll: searchWholeDynamoLogs,
  downloadUrl: dynamoLogHistoryDownloadUrl,
  supportsInitialPod: false,
  emptyHint: () => i18n.t('sources.dynamo.empty', { ns: 'logs' }),
  wholeSearchBanner: () => i18n.t('sources.dynamo.banner', { ns: 'logs' }),
  // 完整 pod 名 + #seq (frontend/worker pod 名区分), 与训练/推理一致
  streamTabLabel: (s) => `${s.pod_name || s.pod_short}-#${s.seq}`,
};

export const rayjobSource: HistorySource = {
  listStreams: fetchRayjobLogStreams,
  fetchHistory: fetchRayjobLogHistory,
  searchAll: searchWholeRayjobLogs,
  downloadUrl: rayjobLogHistoryDownloadUrl,
  supportsInitialPod: false,
  emptyHint: () => i18n.t('sources.rayjob.empty', { ns: 'logs' }),
  wholeSearchBanner: () => i18n.t('sources.rayjob.banner', { ns: 'logs' }),
  // 完整 pod 名 + #seq; head pod 有多条 stream (ray-head 常规 + driver-log-tailer sidecar,
  // driver 也可能多条), pod 名相同, driver 那条插入 -driver 段再接 -#seq 区分。
  streamTabLabel: (s) => {
    const base = s.pod_name || s.pod_short;
    const isDriver = s.stream_name.includes('_driver-log-tailer-');
    return `${base}${isDriver ? '-driver' : ''}-#${s.seq}`;
  },
};

export const llmdSource: HistorySource = {
  listStreams: fetchLlmdLogStreams,
  fetchHistory: fetchLlmdLogHistory,
  searchAll: searchWholeLlmdLogs,
  downloadUrl: llmdLogHistoryDownloadUrl,
  supportsInitialPod: false,
  emptyHint: () => i18n.t('sources.llmd.empty', { ns: 'logs' }),
  wholeSearchBanner: () => i18n.t('sources.llmd.banner', { ns: 'logs' }),
  // 完整 pod 名 + #seq (leader/worker/gateway pod 名区分), 与训练/推理/dynamo 一致
  streamTabLabel: (s) => `${s.pod_name || s.pod_short}-#${s.seq}`,
};

export const devinstanceSource: HistorySource = {
  listStreams: fetchDevInstanceLogStreams,
  fetchHistory: fetchDevInstanceLogHistory,
  searchAll: searchWholeDevInstanceLogs,
  downloadUrl: devInstanceLogHistoryDownloadUrl,
  supportsInitialPod: false,
  emptyHint: () => i18n.t('sources.devinstance.empty', { ns: 'logs' }),
  wholeSearchBanner: () => i18n.t('sources.devinstance.banner', { ns: 'logs' }),
  // 完整 pod 名 + #seq; 同一 pod 有两类容器 (workspace + direct-ssh-init),
  // direct-ssh-init 那条加 -ssh-init 段区分 (照 Ray driver 的 -driver)。
  streamTabLabel: (s) => {
    const base = s.pod_name || s.pod_short;
    const isSsh = s.stream_name.includes('_direct-ssh-init-');
    return `${base}${isSsh ? '-ssh-init' : ''}-#${s.seq}`;
  },
};
