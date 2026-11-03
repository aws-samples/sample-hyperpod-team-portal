/**
 * AuthGate · 路由守门组件.
 *
 * 用法:
 *   <Route element={<AuthGate><MainLayout /></AuthGate>}>
 *     <Route path="workspaces" element={<WorkspaceList />} />
 *     ...
 *   </Route>
 *
 * 逻辑:
 *   1. 挂载时 fetch /api/v1/users/me
 *   2. 200 → 渲染 children (放行)
 *   3. 401 → 触发 startLogin() 跳 Cognito (Hosted UI → IdC)
 */
import { Result, Spin, Button, Alert } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError, apiFetch } from '@/shared/api';
import { useAppStore } from '@/store';
import type { User } from '@/types';
import { fetchAuthConfig, startLogin } from '../login';

type Phase = 'checking' | 'redirecting' | 'authorized' | 'config-missing' | 'error';

interface AuthGateProps {
  children: ReactNode;
}

/** /api/v1/users/me 返回的字段 · 见 services/platform-api UserResponse. */
interface MeResponse {
  id: string;
  email: string;
  display_name: string;
  is_admin: boolean;
}

/** 探测并返回当前用户身份 · 后端 modules/user 已有 /users/me. */
async function probeIdentity(): Promise<MeResponse> {
  return apiFetch<MeResponse>('/users/me');
}

export function AuthGate({ children }: AuthGateProps) {
  const { t } = useTranslation(['auth', 'common']);
  const [phase, setPhase] = useState<Phase>('checking');
  const [error, setError] = useState<string | null>(null);
  const setCurrentUser = useAppStore((s) => s.setCurrentUser);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      try {
        const me = await probeIdentity();
        if (cancelled) return;
        // 把真用户写进 store · 全站 currentUser 单源
        const user: User = {
          id: me.id,
          email: me.email,
          display_name: me.display_name,
          is_admin: Boolean(me.is_admin),
        };
        setCurrentUser(user);
        setPhase('authorized');
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 401) {
          // 401 — 未登录, 拉 auth 配置后跳 Cognito Hosted UI.
          try {
            const cfg = await fetchAuthConfig();
            if (cancelled) return;
            if (!cfg.cognito_domain || !cfg.cognito_client_id) {
              setPhase('config-missing');
              return;
            }
            setPhase('redirecting');
            await startLogin();
          } catch (cfgErr) {
            if (cancelled) return;
            // /api/v1/auth/config 不存在 (后端还没实现) — 给一个友好的报错
            if (cfgErr instanceof ApiError && cfgErr.status === 404) {
              setError(t('gate.configEndpointMissing'));
            } else {
              setError(
                t('gate.configLoadFailed', {
                  error: cfgErr instanceof Error ? cfgErr.message : String(cfgErr),
                }),
              );
            }
            setPhase('error');
          }
        } else {
          setError(e instanceof Error ? e.message : String(e));
          setPhase('error');
        }
      }
    }

    run();
    return () => {
      cancelled = true;
    };
    // setCurrentUser 来自 zustand, 引用稳定
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (phase === 'checking' || phase === 'redirecting') {
    return (
      <div style={fullPageCenter}>
        <Spin size="large" tip={phase === 'checking' ? t('gate.checking') : t('gate.redirecting')} />
      </div>
    );
  }

  if (phase === 'config-missing') {
    return (
      <div style={fullPageCenter}>
        <Result
          status="warning"
          title={t('gate.cognitoNotConfiguredTitle')}
          subTitle={t('gate.cognitoNotConfiguredDesc')}
        />
      </div>
    );
  }

  if (phase === 'error') {
    return (
      <div style={fullPageCenter}>
        <div style={{ maxWidth: 600 }}>
          <Alert
            message={t('gate.checkFailed')}
            description={error ?? 'unknown error'}
            type="error"
            showIcon
            action={
              <Button size="small" onClick={() => window.location.reload()}>
                {t('common:actions.retry')}
              </Button>
            }
          />
        </div>
      </div>
    );
  }

  // phase === 'authorized'
  return <>{children}</>;
}

const fullPageCenter: React.CSSProperties = {
  minHeight: '100vh',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: 24,
};
