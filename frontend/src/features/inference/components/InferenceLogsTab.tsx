import { useState } from 'react';
import { Segmented } from 'antd';
import { useTranslation } from 'react-i18next';
import HistoryLogViewer from '@/features/logs/HistoryLogViewer';
import WholeTaskSearch from '@/features/logs/WholeTaskSearch';
import { inferenceSource } from '@/features/logs/sources';

interface Props {
  inferenceId: string;
}

type LogMode = 'pod' | 'all';

/**
 * 推理历史日志 tab: 分段器切「Pod 日志」/「任务日志(整任务搜索)」。
 * 走公用 HistoryLogViewer / WholeTaskSearch (传 inferenceSource)。
 */
export default function InferenceLogsTab({ inferenceId }: Props) {
  const { t } = useTranslation('inference');
  const [mode, setMode] = useState<LogMode>('pod');

  return (
    <div>
      <Segmented<LogMode>
        style={{ marginBottom: 12 }}
        value={mode}
        onChange={setMode}
        options={[
          { label: t('logs.pod'), value: 'pod' },
          { label: t('logs.all'), value: 'all' },
        ]}
      />
      {mode === 'pod' ? (
        <HistoryLogViewer source={inferenceSource} resourceId={inferenceId} />
      ) : (
        <WholeTaskSearch source={inferenceSource} resourceId={inferenceId} />
      )}
    </div>
  );
}
