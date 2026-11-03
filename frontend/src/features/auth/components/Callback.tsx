/**
 * /auth/callback 路由组件.
 *
 * Cognito Hosted UI 登录成功后 302 回这个路径, URL 形如:
 *   http://localhost:5173/auth/callback?code=ABC&state=YYY
 *
 * 本组件:
 * 1. 调 handleCallback() 处理 code + state, 换 id_token, 存 localStorage
 * 2. 成功 → navigate('/') 跳首页
 * 3. 失败 → 显示错误 + 重试按钮
 */
import { Alert, Button, Spin } from 'antd';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { handleCallback } from '../callback';

// React 18 StrictMode 在 dev 模式故意把 useEffect 跑两次. 我们的 callback 处理涉及:
// 1. sessionStorage 里取走 PKCE verifier (取走就没了)
// 2. 用 code 调 Cognito token endpoint (code 一次性)
// 用模块级 Promise 缓存第一次的结果, 第二次直接复用同一个 Promise.
let callbackPromise: ReturnType<typeof handleCallback> | null = null;

function processCallbackOnce(): ReturnType<typeof handleCallback> {
  if (!callbackPromise) {
    callbackPromise = handleCallback();
  }
  return callbackPromise;
}

export default function Callback() {
  const { t } = useTranslation('auth');
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    processCallbackOnce().then((result) => {
      if (cancelled) return;
      if (result.ok) {
        // 成功 — 跳回首页, replace 防止用户后退又触发一次 callback
        navigate('/', { replace: true });
      } else {
        setError(result.error ?? 'callback failed');
      }
    });
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  if (error) {
    return (
      <div style={fullPageCenter}>
        <div style={{ maxWidth: 600 }}>
          <Alert
            message={t('callback.failedTitle')}
            description={error}
            type="error"
            showIcon
            action={
              <Button
                size="small"
                onClick={() => {
                  callbackPromise = null;
                  navigate('/', { replace: true });
                }}
              >
                {t('callback.backToLogin')}
              </Button>
            }
          />
        </div>
      </div>
    );
  }

  return (
    <div style={fullPageCenter}>
      <Spin size="large" tip={t('callback.processing')} />
    </div>
  );
}

const fullPageCenter: React.CSSProperties = {
  minHeight: '100vh',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: 24,
};
