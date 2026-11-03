import { Alert, Descriptions, Space, Typography } from 'antd';
import { ProCard } from '@ant-design/pro-components';
import { useTranslation } from 'react-i18next';
import type { DynamoDetail } from '../api/types';

const { Paragraph, Text } = Typography;

/**
 * 调用指令卡 · Dynamo frontend SVC (实测 2026-07-11 demo invoke 通):
 *   grove 建 SVC <cr>-frontend (ClusterIP :8000, OpenAI 兼容), served-model-name 作 model 值。
 *   最小切片只有集群内可达; 对外 (VPC 内 ALB) 是第二批 (endpoint_url 就绪后显真实地址)。
 */
export default function InvokeSnippets({ detail }: { detail: DynamoDetail }) {
  const { t } = useTranslation('dynamo');
  const svc = `${detail.k8s_cr_name}-frontend`;
  const host = `${svc}.${detail.k8s_namespace}.svc.cluster.local:8000`;
  // served-model-name 在启动脚本里 (--served-model-name), 详情不单存; 调用时用脚本里的值。
  const model = '<served-model-name>';
  // 译文 samplePrompt 不得含 ' " \ (会被插进单引号 shell 的 JSON body)
  const body = `{"model":"${model}","messages":[{"role":"user","content":"${t('invoke.code.samplePrompt')}"}],"max_tokens":64}`;

  const curl = `curl -s http://${host}/v1/models
curl -s -X POST http://${host}/v1/chat/completions \\
  -H 'Content-Type: application/json' \\
  -d '${body}'`;

  return (
    <ProCard title={t('invoke.title')} bordered>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {detail.endpoint_url ? (
          <Alert
            type="success"
            showIcon
            message={t('invoke.ready')}
            description={
              <Text copyable style={{ fontFamily: 'monospace' }}>
                {detail.endpoint_url}
              </Text>
            }
          />
        ) : (
          <Alert
            type="info"
            showIcon
            message={t('invoke.clusterOnly')}
            description={t('invoke.clusterOnlyDesc')}
          />
        )}
        <div>
          <Text strong style={{ display: 'block', marginBottom: 8 }}>
            {t('invoke.connInfo')}
          </Text>
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label={t('invoke.addrCluster')}>
              <Text copyable={{ text: `http://${host}` }} style={{ fontFamily: 'monospace', fontSize: 12 }}>
                http://{host}
              </Text>
            </Descriptions.Item>
            <Descriptions.Item label={t('invoke.protocol')}>
              <Text>{t('invoke.protocolValue')}</Text>
            </Descriptions.Item>
            <Descriptions.Item label={t('invoke.modelValue')}>
              <Text code>{model}</Text>
            </Descriptions.Item>
          </Descriptions>
        </div>
        <div>
          <Text strong style={{ display: 'block', marginBottom: 8 }}>
            {t('invoke.examples')}
          </Text>
          <Paragraph
            copyable={{ text: curl }}
            style={{
              background: '#f5f5f5',
              padding: 12,
              fontFamily: 'monospace',
              fontSize: 12,
              whiteSpace: 'pre-wrap',
              marginBottom: 0,
            }}
          >
            {curl}
          </Paragraph>
        </div>
      </Space>
    </ProCard>
  );
}
