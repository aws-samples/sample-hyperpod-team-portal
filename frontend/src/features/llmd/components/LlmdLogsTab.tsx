import { useState } from 'react';
import { Segmented } from 'antd';
import { useTranslation } from 'react-i18next';
import HistoryLogViewer from '@/features/logs/HistoryLogViewer';
import WholeTaskSearch from '@/features/logs/WholeTaskSearch';
import { llmdSource } from '@/features/logs/sources';

interface Props {
  llmdId: string;
}

type LogMode = 'pod' | 'all';

/**
 * llm-d 多机推理历史日志 tab: 分段器切「Pod 日志」/「任务日志(整任务搜索)」。
 * 走公用 HistoryLogViewer / WholeTaskSearch (传 llmdSource)。
 * 多机 = 多 pod (LWS leader/worker + gateway), Pod 日志区每 pod 一 tab。
 */
export default function LlmdLogsTab({ llmdId }: Props) {
  const { t } = useTranslation('llmd');
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
        <HistoryLogViewer source={llmdSource} resourceId={llmdId} />
      ) : (
        <WholeTaskSearch source={llmdSource} resourceId={llmdId} />
      )}
    </div>
  );
}
