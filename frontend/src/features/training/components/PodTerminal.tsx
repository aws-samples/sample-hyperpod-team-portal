import { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { useTranslation } from 'react-i18next';
import { withLang } from '@/shared/i18n';

// WS 关闭码 → 文案 key (模块级只存 key, 断开时再翻译)
const CLOSE_REASON_KEY = {
  4401: 'terminal.close.unauthorized',
  4403: 'terminal.close.forbidden',
  4404: 'terminal.close.notFound',
  4408: 'terminal.close.idleTimeout',
  4429: 'terminal.close.tooMany',
  4500: 'terminal.close.noShell',
} as const;

interface Props {
  trainingJobId: string;
  pod: string;
  container?: string;
}

/**
 * Pod 交互终端 (MVP)。xterm ↔ WebSocket ↔ 平台 ↔ k8s exec -it。
 * 后端 channel 协议: 浏览器发文本 = stdin; resize 发 {"resize":{cols,rows}}; 收 stdout/stderr。
 * WS 不能带 header, token 走 ?access_token= (同日志 SSE)。
 */
export default function PodTerminal({ trainingJobId, pod, container = 'trainer' }: Props) {
  const { t } = useTranslation('training');
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: 'monospace',
      theme: { background: '#1e1e1e' },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(ref.current);
    fit.fit();

    const tok = localStorage.getItem('auth_id_token') || '';
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const url =
      `${proto}://${window.location.host}/api/v1/training-jobs/` +
      `${encodeURIComponent(trainingJobId)}/pods/${encodeURIComponent(pod)}/terminal` +
      `?container=${encodeURIComponent(container)}` +
      (tok ? `&access_token=${encodeURIComponent(tok)}` : '');
    const ws = new WebSocket(withLang(url));
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
      const { cols, rows } = term;
      ws.send(JSON.stringify({ resize: { cols, rows } }));
      term.focus();
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') term.write(ev.data);
      else term.write(new Uint8Array(ev.data));
    };
    ws.onclose = (ev) => {
      const reason = Object.hasOwn(CLOSE_REASON_KEY, ev.code)
        ? t(CLOSE_REASON_KEY[ev.code as keyof typeof CLOSE_REASON_KEY])
        : `code=${ev.code}`;
      term.write(`\r\n\x1b[33m${t('terminal.disconnected', { reason })}\x1b[0m\r\n`);
    };

    const onData = term.onData((d) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(d);
    });
    const onResize = () => {
      fit.fit();
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ resize: { cols: term.cols, rows: term.rows } }));
      }
    };
    window.addEventListener('resize', onResize);

    return () => {
      window.removeEventListener('resize', onResize);
      onData.dispose();
      ws.close();
      term.dispose();
    };
  }, [trainingJobId, pod, container, t]);

  return <div ref={ref} style={{ height: '100%', minHeight: 400 }} />;
}
