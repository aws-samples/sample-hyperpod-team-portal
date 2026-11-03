import type { ReactNode } from 'react';
import { Tooltip } from 'antd';
import { QuestionCircleOutlined } from '@ant-design/icons';

// 列表表头加 ? icon + Tooltip 说明含义。tip 支持多行 (用 <ul> 等)。
export default function ColTitle({
  text,
  tip,
}: {
  text: string;
  tip: ReactNode;
}) {
  return (
    <span>
      {text}
      <Tooltip title={tip}>
        <QuestionCircleOutlined
          style={{ marginLeft: 4, color: '#999', cursor: 'help', fontSize: 12 }}
        />
      </Tooltip>
    </span>
  );
}
