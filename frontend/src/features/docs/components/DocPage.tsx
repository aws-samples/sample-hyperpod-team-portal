import type { ReactNode } from 'react';
import { Card, Space, Tag, Typography, theme } from 'antd';
import { useTranslation } from 'react-i18next';
import { PageContainer } from '@ant-design/pro-components';
import PageDescription from '@/shared/ui/PageDescription';

const { Title, Paragraph } = Typography;

interface DocPageProps {
  /** 页面主标题 — 与产品其它页 PageContainer.title 字号一致, 由 PageContainer 渲染。 */
  title: string;
  /** 灰字一行说明, 接 PageContainer 标题下面 (与产品其它页风格统一)。 */
  description: string;
  /** 角标, 例如 "v1 · 2026-06-23"; 与产品其它页 extra 同位摆放。 */
  meta?: ReactNode;
  children: ReactNode;
}

/**
 * 产品文档统一外壳。
 *
 * 设计目标 — 与产品业务页 (Workspace/List, Admin/ResourceTemplates...) 视觉一脉相承:
 *   1. 顶部 PageContainer.title (32px) + PageDescription (灰 13px), 与 SOW 截图站点同款
 *   2. 内容区放进白卡片, 圆角 12 (token Card.borderRadiusLG = 12 与产品其它页一致)
 *   3. 子段落用 <DocSection title> 渲染, 主标 + 副线条, 顺承 logo 渐变品牌色
 *   4. 用户视角 / 技术原理 双 Tag 切片 — 满足"用户能用 + 技术可信"双叙述
 */
export default function DocPage({ title, description, meta, children }: DocPageProps) {
  return (
    <PageContainer title={title} extra={meta}>
      <PageDescription>{description}</PageDescription>
      <Card style={{ borderRadius: 12 }} styles={{ body: { padding: '28px 32px' } }}>
        {children}
      </Card>
    </PageContainer>
  );
}

interface DocSectionProps {
  title: string;
  /** 副标 (英文小字), 同行右对齐, 形成 H1 + EN 双标题感 (与 PRO 站常见排版一致)。 */
  subTitle?: string;
  children: ReactNode;
  /** 章节顶部留白 — 默认 28, 首段 (=0) 由调用方传 0 关闭。 */
  marginTop?: number;
}

/**
 * 章节小节 — 标题左侧 6px 渐变色色条 (logo 同款 #0958d9 → #13c2c2),
 * 配合 18px 粗体标题 + 13px 灰副标。整页风格同步, 不再每页自定义。
 */
export function DocSection({ title, subTitle, children, marginTop = 28 }: DocSectionProps) {
  return (
    <section style={{ marginTop }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 12,
          marginBottom: 12,
        }}
      >
        <span
          style={{
            display: 'inline-block',
            width: 4,
            height: 18,
            borderRadius: 2,
            background:
              'linear-gradient(180deg, #0958d9 0%, #13c2c2 100%)',
            flexShrink: 0,
            transform: 'translateY(2px)',
          }}
        />
        <Title level={4} style={{ margin: 0, fontWeight: 600 }}>
          {title}
        </Title>
        {subTitle && (
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            {subTitle}
          </Typography.Text>
        )}
      </div>
      <div>{children}</div>
    </section>
  );
}

/**
 * 双标签切片 (用户视角 / 技术原理) — 每个功能模块用同一对 Tag 切, 增强一致感。
 * 渲染为一行 Tag, 视觉小, 不压主体内容。
 */
export function PerspectiveTag({ kind }: { kind: 'user' | 'tech' }) {
  const { t } = useTranslation('docs');
  if (kind === 'user') {
    return (
      <Tag color="blue" style={{ borderRadius: 4, marginRight: 0 }}>
        {t('perspective.user')}
      </Tag>
    );
  }
  return (
    <Tag color="cyan" style={{ borderRadius: 4, marginRight: 0 }}>
      {t('perspective.tech')}
    </Tag>
  );
}

interface KeyValueListProps {
  items: Array<{ k: string; v: ReactNode }>;
}

/** 紧凑型 key-value 表 — 用于"组件清单 / 配置项 / 技术约束"等结构化展示。 */
export function KeyValueList({ items }: KeyValueListProps) {
  const { token } = theme.useToken();
  return (
    <div style={{ borderRadius: 8, border: `1px solid ${token.colorBorderSecondary}`, overflow: 'hidden' }}>
      {items.map((it, i) => (
        <div
          key={it.k}
          style={{
            display: 'grid',
            gridTemplateColumns: '180px 1fr',
            padding: '10px 16px',
            background: i % 2 === 0 ? token.colorFillQuaternary : 'transparent',
            borderTop: i === 0 ? 'none' : `1px solid ${token.colorBorderSecondary}`,
            fontSize: 13,
          }}
        >
          <span style={{ color: token.colorTextSecondary }}>{it.k}</span>
          <span style={{ color: token.colorText }}>{it.v}</span>
        </div>
      ))}
    </div>
  );
}

/** 关键概念卡片网格 — 概览页用, 配 icon + 简介, 风格类似 admin Dashboard 顶部 Statistic 区。 */
export function ConceptCard({
  icon,
  title,
  desc,
}: {
  icon: ReactNode;
  title: string;
  desc: string;
}) {
  const { token } = theme.useToken();
  return (
    <Card
      style={{ borderRadius: 12, height: '100%' }}
      styles={{ body: { padding: 20 } }}
    >
      <Space align="center" size={10} style={{ marginBottom: 8 }}>
        <span
          style={{
            width: 36,
            height: 36,
            borderRadius: 10,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontSize: 18,
            background:
              'linear-gradient(135deg, #0958d9 0%, #13c2c2 100%)',
          }}
        >
          {icon}
        </span>
        <span style={{ fontSize: 16, fontWeight: 600, color: token.colorText }}>
          {title}
        </span>
      </Space>
      <Paragraph
        type="secondary"
        style={{ marginBottom: 0, fontSize: 13, lineHeight: '22px' }}
      >
        {desc}
      </Paragraph>
    </Card>
  );
}

/** 技术原理段 — 灰底 + 左色条, 与上下用户视角段视觉分层。 */
export function TechBlock({ children }: { children: ReactNode }) {
  const { token } = theme.useToken();
  return (
    <div
      style={{
        marginTop: 12,
        padding: '14px 18px',
        borderRadius: 8,
        background: token.colorFillQuaternary,
        borderLeft: '2px solid #87e8de',
        fontSize: 13,
        lineHeight: '22px',
        color: token.colorText,
      }}
    >
      <div style={{ marginBottom: 6 }}>
        <PerspectiveTag kind="tech" />
      </div>
      {children}
    </div>
  );
}

/** 用户视角段 — 白底 + 浅边框, 与 TechBlock 形成对照, 默认承载叙述文字。 */
export function UserBlock({ children }: { children: ReactNode }) {
  const { token } = theme.useToken();
  return (
    <div
      style={{
        marginTop: 12,
        padding: '14px 18px',
        borderRadius: 8,
        background: token.colorBgContainer,
        border: `1px solid ${token.colorBorderSecondary}`,
        borderLeft: '2px solid #91caff',
        fontSize: 13,
        lineHeight: '22px',
        color: token.colorText,
      }}
    >
      <div style={{ marginBottom: 6 }}>
        <PerspectiveTag kind="user" />
      </div>
      {children}
    </div>
  );
}
