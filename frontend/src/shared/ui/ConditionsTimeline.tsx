import { Empty, Space, Tag, Timeline, Typography } from 'antd';
import dayjs from 'dayjs';
import { useTranslation } from 'react-i18next';

const { Text } = Typography;

/**
 * 跨模块通用的 K8s Conditions 时间线。
 *
 * 训练 / 推理 / 开发机三处 CR 的 `.status.conditions` 语义一致
 * (type / status / reason / message + 转换时间), 但后端序列化时间字段名不统一:
 *   - 训练: last_transition_time (下划线)
 *   - 推理 / 开发机: lastTransitionTime (驼峰)
 * 这里同时读两种写法做兼容, 不要求后端改字段。
 */
export interface TimelineCondition {
  type?: string;
  status?: string;
  reason?: string | null;
  message?: string | null;
  lastTransitionTime?: string | null;
  last_transition_time?: string | null;
}

function transitionTime(c: TimelineCondition): string | null {
  return c.lastTransitionTime ?? c.last_transition_time ?? null;
}

export interface ConditionsTimelineProps {
  conditions: TimelineCondition[];
  /** 默认按转换时间倒序 (最新在上); 传 false 保留原始顺序 */
  sortDescending?: boolean;
  emptyText?: string;
}

export default function ConditionsTimeline({
  conditions,
  sortDescending = true,
  emptyText,
}: ConditionsTimelineProps) {
  const { t } = useTranslation('common');
  if (!conditions || conditions.length === 0) {
    return <Empty description={emptyText ?? t('conditionsTimeline.empty')} />;
  }

  const items = sortDescending
    ? [...conditions].sort((a, b) => {
        const ta = transitionTime(a) ? dayjs(transitionTime(a)!).valueOf() : 0;
        const tb = transitionTime(b) ? dayjs(transitionTime(b)!).valueOf() : 0;
        return tb - ta;
      })
    : conditions;

  return (
    <Timeline
      items={items.map((c) => {
        const time = transitionTime(c);
        return {
          color:
            c.status === 'True'
              ? c.type === 'Degraded'
                ? 'red'
                : 'green'
              : 'gray',
          children: (
            <Space direction="vertical" size={0}>
              <Space>
                <Text strong>{c.type}</Text>
                <Tag color={c.status === 'True' ? 'green' : 'default'}>{c.status}</Tag>
                {c.reason && <Tag>{c.reason}</Tag>}
              </Space>
              {c.message && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {c.message}
                </Text>
              )}
              {time && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {dayjs(time).format('YYYY-MM-DD HH:mm:ss')}
                </Text>
              )}
            </Space>
          ),
        };
      })}
    />
  );
}
