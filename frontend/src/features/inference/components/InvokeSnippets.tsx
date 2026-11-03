import { Alert, Descriptions, Space, Tabs, Typography } from 'antd';
import { ProCard } from '@ant-design/pro-components';
import { useTranslation } from 'react-i18next';
import type { InferenceDetail } from '../api/types';

const { Paragraph, Text } = Typography;

/**
 * 调用指令卡 · 三种访问方式 (均实测验证 2026-06):
 *   ① 集群内 (开发机 Space / 同集群 Pod): ClusterIP routing-service, 明文 HTTP, 全 path, 无鉴权。
 *   ② VPC 内 (含 VPN / peering 打通网段): internal ALB, HTTPS 自签证书 (-k), 仅
 *      /v1/chat/completions (operator ingress 只配这一条 rule), 无鉴权。
 *   ③ 公网 (SageMaker endpoint): SigV4 签名, 仅在创建时勾选「公网访问」才有。
 *
 * SGLang model 值 = /opt/ml/model (单模型不严格校验 model 名)。
 */

const DEFAULT_MODEL = '/opt/ml/model';

const CHAT_PATH = 'v1/chat/completions';

export default function InvokeSnippets({ detail }: { detail: InferenceDetail }) {
  const { t } = useTranslation('inference');
  const svc = `${detail.k8s_endpoint_name}-routing-service`;
  const clusterHost = `${svc}:443`;
  const clusterHostFqdn = `${svc}.${detail.k8s_namespace}.svc.cluster.local:443`;
  const ingressName = `alb-${detail.k8s_endpoint_name}`;
  // 译文 samplePrompt 不得含 ' " \ (会被插进单引号 shell 的 JSON body)
  const chatBody = `{"model":"${DEFAULT_MODEL}","messages":[{"role":"user","content":"${t('invoke.code.samplePrompt')}"}],"max_tokens":64}`;

  const clusterCurl = `curl -s http://${clusterHost}/v1/models
curl -s -X POST http://${clusterHost}/${CHAT_PATH} \\
  -H 'Content-Type: application/json' \\
  -d '${chatBody}'`;

  const albHost = detail.alb_dns;

  const albLookup = `# ${t('invoke.code.albLookupComment')}
kubectl get ingress ${ingressName} -n ${detail.k8s_namespace} \\
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'`;

  const albCurl = albHost
    ? `curl -sk -X POST "https://${albHost}/${CHAT_PATH}" \\
  -H 'Content-Type: application/json' \\
  -d '${chatBody}'`
    : `ALB=<${t('invoke.code.albPlaceholder')}>
curl -sk -X POST "https://$ALB/${CHAT_PATH}" \\
  -H 'Content-Type: application/json' \\
  -d '${chatBody}'`;

  const smCli =`printf '%s' '${chatBody}' > /tmp/body.json
# ${t('invoke.code.awsProfileComment')}
AWS_PROFILE=<your-profile> aws sagemaker-runtime invoke-endpoint \\
  --endpoint-name ${detail.k8s_endpoint_name} \\
  --region us-west-2 \\
  --content-type application/json \\
  --body fileb:///tmp/body.json \\
  /tmp/out.json && cat /tmp/out.json`;

  const clusterConn = (
    <ConnInfo
      rows={[
        [t('invoke.rows.addrSameNs'), `http://${clusterHost}`, t('invoke.rows.sameNsNote')],
        [t('invoke.rows.addrCrossNs'), `http://${clusterHostFqdn}`, t('invoke.rows.crossNsNote')],
      ]}
    />
  );

  const albConn = (
    <ConnInfo
      rows={[
        [
          t('invoke.rows.addr'),
          albHost ? `https://${albHost}` : t('invoke.rows.albPending'),
          '',
        ],
      ]}
    />
  );

  const smConn = (
    <ConnInfo
      rows={[
        [t('invoke.rows.endpointName'), detail.k8s_endpoint_name, ''],
        [t('invoke.rows.protocol'), t('invoke.rows.protocolValue'), ''],
        ['Region', 'us-west-2', ''],
        [t('invoke.rows.credential'), 'IAM sagemaker:InvokeEndpoint', t('invoke.rows.credentialNote')],
      ]}
    />
  );

  return (
    <ProCard title={t('invoke.title')} bordered>
      <Tabs
        items={[
          {
            key: 'alb',
            label: t('invoke.tabs.alb'),
            children: (
              <Section conn={albConn}>
                {!albHost && <CodeBlock text={albLookup} note={t('invoke.notes.albLookup')} />}
                <CodeBlock text={albCurl} note={t('invoke.notes.albCall')} />
              </Section>
            ),
          },
          {
            key: 'sagemaker',
            label: t('invoke.tabs.sagemaker'),
            children: detail.public_endpoint ? (
              <Section conn={smConn}>
                <CodeBlock text={smCli} note={t('invoke.notes.smCli')} />
              </Section>
            ) : (
              <Alert
                type="info"
                showIcon
                message={t('invoke.disabled.title')}
                description={t('invoke.disabled.desc')}
              />
            ),
          },
          {
            key: 'cluster',
            label: t('invoke.tabs.cluster'),
            children: (
              <Section conn={clusterConn}>
                <CodeBlock text={clusterCurl} note="curl" />
              </Section>
            ),
          },
        ]}
      />
    </ProCard>
  );
}

function Section({
  conn,
  children,
}: {
  conn: React.ReactNode;
  children: React.ReactNode;
}) {
  const { t } = useTranslation('inference');
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <div>
        <Text strong style={{ display: 'block', marginBottom: 8 }}>
          {t('invoke.connInfo')}
        </Text>
        {conn}
      </div>
      <div>
        <Text strong style={{ display: 'block', marginBottom: 8 }}>
          {t('invoke.examples')}
        </Text>
        <Space direction="vertical" size="small" style={{ width: '100%' }}>
          {children}
        </Space>
      </div>
    </Space>
  );
}

function ConnInfo({ rows }: { rows: [string, string, string][] }) {
  return (
    <Descriptions bordered size="small" column={1}>
      {rows.map(([label, value, note]) => (
        <Descriptions.Item key={label} label={label}>
          <Text copyable={{ text: value }} style={{ fontFamily: 'monospace', fontSize: 12 }}>
            {value}
          </Text>
          {note && (
            <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
              {note}
            </Text>
          )}
        </Descriptions.Item>
      ))}
    </Descriptions>
  );
}

function CodeBlock({ text, note }: { text: string; note?: string }) {
  return (
    <>
      {note && (
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
          {note}
        </Text>
      )}
      <Paragraph
        copyable={{ text }}
        style={{
          background: '#f5f5f5',
          padding: 12,
          fontFamily: 'monospace',
          fontSize: 12,
          whiteSpace: 'pre-wrap',
          marginBottom: 0,
        }}
      >
        {text}
      </Paragraph>
    </>
  );
}
