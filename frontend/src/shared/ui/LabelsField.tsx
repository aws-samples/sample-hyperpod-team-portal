import { Button, Col, Form, Input, Row, Typography } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import i18n from '@/shared/i18n';

const RESERVED_PREFIXES = [
  'platform.hyperpod.io/',
  'kueue.x-k8s.io/',
  'sagemaker.',
  'kubernetes.io/',
  'k8s.io/',
  'app.kubernetes.io/',
];

const NAME_RE = /^[a-zA-Z0-9]([a-zA-Z0-9._-]{0,61}[a-zA-Z0-9])?$/;

function validateKey(v: string): string | null {
  const key = (v || '').trim();
  if (!key) return i18n.t('labelsField.keyRequired', { ns: 'common' });
  if (RESERVED_PREFIXES.some((p) => key.toLowerCase().startsWith(p)))
    return i18n.t('labelsField.reservedPrefix', { ns: 'common' });
  const name = key.includes('/') ? key.slice(key.indexOf('/') + 1) : key;
  if (!NAME_RE.test(name)) return i18n.t('labelsField.nameRule', { ns: 'common' });
  return null;
}

function validateValue(v: string): string | null {
  const val = (v || '').trim();
  if (val && !NAME_RE.test(val)) return i18n.t('labelsField.nameRule', { ns: 'common' });
  return null;
}

/**
 * 自定义 label 编辑器 (训练/推理共用)。form 字段 = label_pairs: {key,value}[]。
 * 裸 key, 前端即时校验保留前缀 + RFC; 后端 validate_user_labels 是安全闸。
 */
export default function LabelsField({ name = 'label_pairs' }: { name?: string }) {
  const { t } = useTranslation('common');
  return (
    <Form.Item
      label={t('labelsField.label')}
      tooltip={t('labelsField.tooltip')}
    >
      <Form.List name={name}>
        {(fields, { add, remove }) => (
          <>
            {fields.map(({ key, name: n, ...rest }) => (
              <Row gutter={8} key={key} align="top">
                <Col span={7}>
                  <Form.Item
                    {...rest}
                    name={[n, 'key']}
                    rules={[
                      {
                        validator: (_, v) => {
                          const err = validateKey(v);
                          return err ? Promise.reject(new Error(err)) : Promise.resolve();
                        },
                      },
                    ]}
                  >
                    <Input placeholder="key" />
                  </Form.Item>
                </Col>
                <Col span={7}>
                  <Form.Item
                    {...rest}
                    name={[n, 'value']}
                    rules={[
                      {
                        validator: (_, v) => {
                          const err = validateValue(v);
                          return err ? Promise.reject(new Error(err)) : Promise.resolve();
                        },
                      },
                    ]}
                  >
                    <Input placeholder="value" />
                  </Form.Item>
                </Col>
                <Col span={2}>
                  <MinusCircleOutlined
                    onClick={() => remove(n)}
                    style={{ fontSize: 16, color: '#999', marginTop: 8 }}
                  />
                </Col>
              </Row>
            ))}
            {fields.length < 10 && (
              <Button
                type="dashed"
                size="small"
                onClick={() => add({ key: '', value: '' })}
                icon={<PlusOutlined />}
              >
                {t('labelsField.add')}
              </Button>
            )}
            {fields.length >= 10 && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {t('labelsField.max')}
              </Typography.Text>
            )}
          </>
        )}
      </Form.List>
    </Form.Item>
  );
}
