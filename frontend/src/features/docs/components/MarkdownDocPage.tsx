import type { ReactNode } from 'react';
import { Card } from 'antd';
import { PageContainer } from '@ant-design/pro-components';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import PageDescription from '@/shared/ui/PageDescription';

interface MarkdownDocPageProps {
  title: string;
  description: string;
  meta?: ReactNode;
  /** Markdown 原文 (通常来自 `?raw` 静态导入), 按 GFM 语法渲染 (表格/代码块/任务列表)。 */
  markdown: string;
}

/**
 * 外部 markdown 文档 (Runbook / 排障手册等) 的统一外壳。
 *
 * 与 DocPage 共享顶部结构 (PageContainer + PageDescription + 圆角卡片),
 * 但正文直接渲染 markdown 原文 — 这类文档以表格/代码块/步骤列表为主,
 * 拆成 DocSection/UserBlock/TechBlock 逐段手写的性价比低, 后续更新只需替换 md 源文件。
 * 排版规则见 index.css 里的 `.markdown-doc-body`。
 */
export default function MarkdownDocPage({
  title,
  description,
  meta,
  markdown,
}: MarkdownDocPageProps) {
  return (
    <PageContainer title={title} extra={meta}>
      <PageDescription>{description}</PageDescription>
      <Card style={{ borderRadius: 12 }} styles={{ body: { padding: '28px 32px' } }}>
        <div className="markdown-doc-body">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
        </div>
      </Card>
    </PageContainer>
  );
}
