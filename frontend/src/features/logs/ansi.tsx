import { useMemo } from 'react';
import type { CSSProperties } from 'react';
import Anser from 'anser';

/**
 * 把带 ANSI 转义序列 (\x1b[..m) 的日志文本渲染成彩色 span。
 *
 * 背景: SGLang gateway (Rust `tracing`) 等进程默认彩色输出, FluentBit 原样收进
 * CloudWatch。历史日志区是纯 DOM span, 不解释这些控制码 → 显示成乱码。这里用
 * anser 解析成 JSON 片段, 再映射为内联样式, 不走 dangerouslySetInnerHTML (避免 XSS)。
 *
 * 说明:
 * - fg/bg 是 anser 给的 "R, G, B" 字符串 (标准 xterm 调色板), 明暗主题都能读。
 * - dim 走 opacity (ANSI dim 是"减弱"而非具体色), 与 fg 叠加。
 * - 光标移动等非 SGR 码 anser 会自动忽略。
 */

const DECORATION_STYLE: Partial<Record<string, CSSProperties>> = {
  bold: { fontWeight: 600 },
  dim: { opacity: 0.6 },
  italic: { fontStyle: 'italic' },
  underline: { textDecoration: 'underline' },
  strikethrough: { textDecoration: 'line-through' },
};

function entryStyle(e: Anser.AnserJsonEntry): CSSProperties {
  const s: CSSProperties = {};
  if (e.fg) s.color = `rgb(${e.fg})`;
  if (e.bg) s.background = `rgb(${e.bg})`;
  for (const d of e.decorations) Object.assign(s, DECORATION_STYLE[d]);
  return s;
}

/** 单行日志: 解析 ANSI → 彩色 span 序列。无控制码时退化为纯文本片段。 */
export function AnsiLine({ text }: { text: string }) {
  const parts = useMemo(
    () => Anser.ansiToJson(text, { json: true, remove_empty: true, use_classes: false }),
    [text],
  );
  return (
    <>
      {parts.map((e, i) => {
        const style = entryStyle(e);
        return Object.keys(style).length ? (
          <span key={i} style={style}>
            {e.content}
          </span>
        ) : (
          <span key={i}>{e.content}</span>
        );
      })}
    </>
  );
}
