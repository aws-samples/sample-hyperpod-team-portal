import { useState } from 'react';
import { Segmented } from 'antd';
import { useTranslation } from 'react-i18next';
import HistoryLogViewer from '@/features/logs/HistoryLogViewer';
import WholeTaskSearch from '@/features/logs/WholeTaskSearch';
import { rayjobSource } from '@/features/logs/sources';

interface Props {
  rayjobId: string;
}

type LogMode = 'pod' | 'all';

/**
 * Ray 训练历史日志 tab: 分段器切「Pod 日志」/「任务日志(整任务搜索)」。
 * 走公用 HistoryLogViewer / WholeTaskSearch (传 rayjobSource)。
 * 多机 = 多 pod (head + worker), Pod 日志区每 pod 一 tab。
 */
export default function RayJobLogsTab({ rayjobId }: Props) {
  const { t } = useTranslation('rayjob');
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
        <HistoryLogViewer source={rayjobSource} resourceId={rayjobId} />
      ) : (
        <WholeTaskSearch source={rayjobSource} resourceId={rayjobId} />
      )}
    </div>
  );
}
