import { Alert } from 'antd';
import { useTranslation } from 'react-i18next';
import MonitoringTabPanel from '@/shared/ui/metrics/MonitoringTabPanel';
import { listTrainingTemplates } from '@/api/monitoring';

interface Props {
  trainingJobId: string;
  height?: number;
}

/**
 * Training job monitoring charts container.
 *
 * Wraps the shared `MonitoringTabPanel` with the training-scoped template
 * loader. Data pipeline: in-cluster Prometheus (DCGM + node-exporter +
 * cAdvisor) → AMP → platform-api `/monitoring/training/{id}/templates` →
 * `PromRangeChart`. Panels auto-refresh every 20-30s.
 *
 * Note on boundary: `MonitoringTabPanel` lives under `@/components/metrics/`
 * and `listTrainingTemplates` under `@/api/monitoring` — their permanent
 * home (observability feature vs shared/ui) is pending the Wave 3
 * observability decision (see `shared/ui/README.md`).
 */
export default function MetricsCharts({
  trainingJobId,
  height = 240,
}: Props) {
  const { t } = useTranslation('training');
  return (
    <MonitoringTabPanel
      loadTemplates={() => listTrainingTemplates(trainingJobId)}
      depKey={trainingJobId}
      height={height}
      showDimensionSwitch
      banner={
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('metrics.banner')}
        />
      }
    />
  );
}
