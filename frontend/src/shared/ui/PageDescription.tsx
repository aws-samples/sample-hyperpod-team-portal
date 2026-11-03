import type { ReactNode } from 'react';
import { theme } from 'antd';

// 页面标题下统一描述行 · 灰字 13px, 与主体留间距。位于 PageContainer 主体最上方。
export default function PageDescription({ children }: { children: ReactNode }) {
  const { token } = theme.useToken();
  return (
    <div
      style={{
        color: token.colorTextSecondary,
        fontSize: 13,
        marginTop: -8,
        marginBottom: 16,
      }}
    >
      {children}
    </div>
  );
}
