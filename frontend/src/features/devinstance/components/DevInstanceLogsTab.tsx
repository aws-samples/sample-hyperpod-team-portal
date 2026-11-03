import { useState } from 'react';
import { Segmented } from 'antd';
import { useTranslation } from 'react-i18next';
import HistoryLogViewer from '@/features/logs/HistoryLogViewer';
import WholeTaskSearch from '@/features/logs/WholeTaskSearch';
import { devinstanceSource } from '@/features/logs/sources';

interface Props {
  devInstanceId: string;
}

type LogMode = 'pod' | 'all';

/**
 * 开发机历史日志 tab: 分段器切「Pod 日志」/「任务日志(整任务搜索)」。
 * 走公用 HistoryLogViewer / WholeTaskSearch (传 devinstanceSource)。
 * 每代 pod 有 workspace (主容器) + direct-ssh-init (SSH 建连) 两条 stream。
 */
export default function DevInstanceLogsTab({ devInstanceId }: Props) {
  const { t } = useTranslation('devinstance');
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
        <HistoryLogViewer source={devinstanceSource} resourceId={devInstanceId} />
      ) : (
        <WholeTaskSearch source={devinstanceSource} resourceId={devInstanceId} />
      )}
    </div>
  );
}
