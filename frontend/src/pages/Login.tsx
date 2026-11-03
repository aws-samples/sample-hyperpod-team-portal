import { Button, Card, Space, Typography, Divider } from 'antd';
import {
  CloudOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  RocketOutlined,
  ExperimentOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { Trans, useTranslation } from 'react-i18next';
import { useAppStore } from '@/store';

const { Title, Text, Paragraph } = Typography;

/**
 * Cognito SSO login page — mock flow that jumps straight to the workspace
 * list. Left side shows the product slogan, right side holds the login card.
 */
export default function Login() {
  const { t } = useTranslation('auth');
  const navigate = useNavigate();
  const wsId = useAppStore((s) => s.currentWorkspaceId);

  const loginWithSso = () => {
    // Prototype only — no real OIDC round-trip.
    navigate('/workspaces');
  };

  const loginWithIdentityCenter = () => {
    navigate(`/workspaces/${wsId}`);
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        background:
          'linear-gradient(135deg, #06142d 0%, #0b2f6b 45%, #0958d9 100%)',
        color: '#fff',
      }}
    >
      {/* Left hero panel */}
      <div
        className="login-hero"
        style={{
          flex: 1,
          padding: '80px 72px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          minWidth: 0,
        }}
      >
        <div className="login-hero-grid" aria-hidden />
        <Space align="center" size={12}>
          <ThunderboltOutlined style={{ fontSize: 36, color: '#69b1ff' }} />
          <span style={{ fontSize: 22, fontWeight: 600 }}>
            HyperPod Platform
          </span>
        </Space>

        <div>
          <Title
            level={1}
            style={{
              color: '#fff',
              fontSize: 48,
              marginBottom: 16,
              fontWeight: 700,
            }}
          >
            Next-gen ML Infrastructure
          </Title>
          <Title
            level={3}
            style={{ color: 'rgba(255,255,255,0.85)', marginTop: 0 }}
          >
            PAI experience, on AWS.
          </Title>
          <Paragraph
            style={{
              color: 'rgba(255,255,255,0.7)',
              fontSize: 16,
              maxWidth: 520,
              marginTop: 24,
            }}
          >
            {t('login.tagline')}
          </Paragraph>

          <Space direction="vertical" size={12} style={{ marginTop: 40 }}>
            <Space>
              <RocketOutlined style={{ color: '#69b1ff' }} />
              <Text style={{ color: 'rgba(255,255,255,0.85)' }}>
                {t('login.features.devInstance')}
              </Text>
            </Space>
            <Space>
              <ExperimentOutlined style={{ color: '#69b1ff' }} />
              <Text style={{ color: 'rgba(255,255,255,0.85)' }}>
                {t('login.features.training')}
              </Text>
            </Space>
            <Space>
              <CloudOutlined style={{ color: '#69b1ff' }} />
              <Text style={{ color: 'rgba(255,255,255,0.85)' }}>
                {t('login.features.inference')}
              </Text>
            </Space>
          </Space>
        </div>

        <Text style={{ color: 'rgba(255,255,255,0.5)', fontSize: 12 }}>
          v2.0.0 · © 2026 HyperPod Platform
        </Text>
      </div>

      {/* Right login card */}
      <div
        style={{
          width: 480,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '48px 64px',
          background: 'rgba(255,255,255,0.04)',
          backdropFilter: 'blur(8px)',
        }}
      >
        <Card
          style={{
            width: '100%',
            borderRadius: 16,
            boxShadow:
              '0 24px 60px -12px rgba(0, 0, 0, 0.45), 0 8px 24px -8px rgba(9, 88, 217, 0.35)',
            border: '1px solid rgba(255,255,255,0.08)',
          }}
          styles={{ body: { padding: 40 } }}
        >
          <div style={{ textAlign: 'center', marginBottom: 32 }}>
            <Title level={3} style={{ marginBottom: 4 }}>
              {t('login.welcome')}
            </Title>
            <Text type="secondary">{t('login.subtitle')}</Text>
          </div>

          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Button
              type="primary"
              size="large"
              block
              icon={<SafetyCertificateOutlined />}
              onClick={loginWithSso}
              className="btn-gradient-primary"
              style={{ height: 48, fontSize: 15, fontWeight: 500 }}
            >
              {t('login.ssoButton')}
            </Button>

            <Button
              size="large"
              block
              icon={<CloudOutlined />}
              onClick={loginWithIdentityCenter}
              style={{ height: 48, fontSize: 15 }}
            >
              AWS IAM Identity Center
            </Button>
          </Space>

          <Divider plain style={{ fontSize: 12, color: '#999' }}>
            {t('login.securityTitle')}
          </Divider>

          <Paragraph
            type="secondary"
            style={{ fontSize: 12, marginBottom: 0, textAlign: 'center' }}
          >
            {t('login.securityNote')}
            <br />
            <Trans i18nKey="login.contact" ns="auth" components={{ mail: <Text code /> }} />
          </Paragraph>
        </Card>
      </div>
    </div>
  );
}
