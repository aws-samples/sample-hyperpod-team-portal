import { PageContainer, ProCard } from '@ant-design/pro-components';
import { Empty } from 'antd';

interface Props {
  title: string;
  stage?: string;
}

/**
 * Shared placeholder used by all Stage-1 skeleton pages.
 * Stage-2 agents will replace these with real implementations.
 */
export default function Placeholder({ title, stage = 'Stage 2' }: Props) {
  return (
    <PageContainer title={title}>
      <ProCard style={{ minHeight: 480 }}>
        <Empty
          description={`Coming soon - filled by ${stage} agent`}
          imageStyle={{ height: 120 }}
        />
      </ProCard>
    </PageContainer>
  );
}
