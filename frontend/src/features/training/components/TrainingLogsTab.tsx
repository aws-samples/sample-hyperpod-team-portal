import { useEffect, useState } from 'react';
import { Segmented } from 'antd';
import { useTranslation } from 'react-i18next';
import HistoryLogViewer from '@/features/logs/HistoryLogViewer';
import WholeTaskSearch from '@/features/logs/WholeTaskSearch';
import { trainingSource } from '@/features/logs/sources';

interface Props {
  trainingJobId: string;
  /** 从实时日志抽屉"在日志页查看"跳来: 预选该 pod (强制单 Pod 模式)。 */
  initialPod?: string;
}

type LogMode = 'pod' | 'all';

/**
 * 日志 tab 容器: 顶部分段器切换「单 Pod」/「全局搜索(整任务)」。
 * 走公用 HistoryLogViewer / WholeTaskSearch (传 trainingSource)。
 */
export default function TrainingLogsTab({ trainingJobId, initialPod }: Props) {
  const { t } = useTranslation('training');
  const [mode, setMode] = useState<LogMode>('pod');

  // 从抽屉跳转 (带 initialPod) → 强制切回单 Pod 模式
  useEffect(() => {
    if (initialPod) setMode('pod');
  }, [initialPod]);

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
        <HistoryLogViewer
          source={trainingSource}
          resourceId={trainingJobId}
          initialPod={initialPod}
        />
      ) : (
        <WholeTaskSearch source={trainingSource} resourceId={trainingJobId} />
      )}
    </div>
  );
}
