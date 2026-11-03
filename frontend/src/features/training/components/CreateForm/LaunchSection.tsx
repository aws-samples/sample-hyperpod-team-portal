import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Trans, useTranslation } from 'react-i18next';
import { Button, Col, Drawer, Form, Input, Row, Select, Tooltip } from 'antd';
import {
  MinusCircleOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons';
import ScriptEditor from './ScriptEditor';
import { getSecretView } from '@/api/secret';

import type { ReactNode } from 'react';

// HyperPod Training Operator 保留环境变量, 用户不能在 env 设 (设了 webhook 拒 403)。
export const RESERVED_ENV_KEYS = ['NNODES', 'NPROC_PER_NODE', 'JOB_NAME'];

// 示例脚本整段放在文案表 (create.launch.scripts.*): 里面的注释是给用户看的文字, 随语言切换;
// 命令本身在 zh-CN / en-US 两份里必须逐字节一致, 改脚本时两边同步改。

function SectionHeading({ title, help }: { title: ReactNode; help: ReactNode }) {
  return (
    <div style={{ fontWeight: 500, marginBottom: 12 }}>
      {title}
      <Tooltip title={help}>
        <QuestionCircleOutlined style={{ color: '#999', marginLeft: 6, cursor: 'help' }} />
      </Tooltip>
    </div>
  );
}

export type ScriptExampleKind = 'none' | 'default' | 'wrap';

export interface LaunchSectionProps {
  exampleKind: ScriptExampleKind;
  onPickExample: (k: ScriptExampleKind) => void;
}

/**
 * 启动配置 (原 step3): 直接编写启动脚本 (整段作 command) + 环境变量 KV。
 * script_inline / env_pairs 绑 form; 示例面板 (默认 / 裸代码封装) 展开态由 index 经 props 传。
 */
export default function LaunchSection({
  exampleKind,
  onPickExample,
}: LaunchSectionProps) {
  const { t } = useTranslation(['training', 'common']);
  const { wsId = '' } = useParams();
  const showExample = exampleKind !== 'none';
  const [secretKeys, setSecretKeys] = useState<string[]>([]);
  useEffect(() => {
    if (!wsId) return;
    getSecretView(wsId).then((v) => setSecretKeys(v.keys)).catch(() => setSecretKeys([]));
  }, [wsId]);
  return (
    <>
      <SectionHeading
        title={t('create.launch.scriptHeading')}
        help={t('create.launch.scriptHelp')}
      />
      <Form.Item
        name="script_inline"
        label={t('create.launch.scriptLabel')}
        tooltip={
          <span>
            <Trans
              i18nKey="create.launch.scriptTooltip"
              ns="training"
              components={{ br: <br /> }}
            />
          </span>
        }
        rules={[{ required: true, message: t('create.launch.scriptRequired') }]}
        extra={
          <Button.Group size="small">
            <Button
              type="link"
              style={{ padding: 0 }}
              onClick={() => onPickExample('default')}
            >
              {t('create.launch.exampleDefault')}
            </Button>
            <Button
              type="link"
              style={{ padding: '0 0 0 12px' }}
              onClick={() => onPickExample('wrap')}
            >
              {t('create.launch.exampleWrap')}
            </Button>
          </Button.Group>
        }
      >
        <ScriptEditor height={190} />
      </Form.Item>

      {/* 示例从侧边抽屉划出 (只读参考), 不再内联占右栏 — 与 Kueue 详情一致 */}
      <Drawer
        title={
          exampleKind === 'wrap'
            ? t('create.launch.exampleWrap')
            : t('create.launch.exampleDefault')
        }
        width={760}
        open={showExample}
        onClose={() => onPickExample('none')}
      >
        <div style={{ marginBottom: 12, color: '#888', fontSize: 13, lineHeight: 1.6 }}>
          {exampleKind === 'wrap' ? (
            <Trans
              i18nKey="create.launch.exampleWrapDesc"
              ns="training"
              components={{
                code: <code />,
                warn: <span style={{ color: '#fa8c16' }} />,
              }}
            />
          ) : (
            t('create.launch.exampleDefaultDesc')
          )}
        </div>
        <ScriptEditor
          readOnly
          height="calc(100vh - 200px)"
          value={
            exampleKind === 'wrap'
              ? t('create.launch.scripts.wrap')
              : t('create.launch.scripts.inline')
          }
        />
      </Drawer>

      {/* EFA 网卡数已并入「计算资源」的资源模板锁定 (每节点规格 · 模板锁定),
          不再在此手填 — 与 GPU/CPU/内存 一致由 admin 维护的模板统一管控。 */}

      <SectionHeading
        title={t('create.launch.envHeading')}
        help={t('create.launch.envHelp')}
      />
      <Form.List name="env_pairs">
        {(fields, { add, remove }) => (
          <>
            {fields.map(({ key, name, ...rest }) => (
              <Row gutter={8} key={key} align="middle">
                <Col span={10}>
                  <Form.Item
                    {...rest}
                    name={[name, 'key']}
                    rules={[
                      { required: true, message: 'key' },
                      {
                        validator: (_, v) =>
                          RESERVED_ENV_KEYS.includes(String(v || '').trim().toUpperCase())
                            ? Promise.reject(
                                new Error(t('create.launch.envReserved')),
                              )
                            : Promise.resolve(),
                      },
                    ]}
                  >
                    <Input placeholder="key e.g. WANDB_PROJECT" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item {...rest} name={[name, 'value']}>
                    <Input placeholder="value" />
                  </Form.Item>
                </Col>
                <Col span={2}>
                  <MinusCircleOutlined
                    onClick={() => remove(name)}
                    style={{ fontSize: 18, color: '#999' }}
                  />
                </Col>
              </Row>
            ))}
            <Button type="dashed" onClick={() => add({ key: '', value: '' })} icon={<PlusOutlined />} block>
              {t('create.launch.envAdd')}
            </Button>
          </>
        )}
      </Form.List>

      <SectionHeading
        title={t('create.launch.secretHeading')}
        help={t('create.launch.secretHelp')}
      />
      <Form.List name="env_secret_pairs">
        {(fields, { add, remove }) => (
          <>
            {fields.map(({ key, name, ...rest }) => (
              <Row gutter={8} key={key} align="middle">
                <Col span={22}>
                  <Form.Item {...rest} name={[name, 'secret_key']} rules={[{ required: true, message: t('create.launch.secretKeyRequired') }]}>
                    <Select
                      placeholder={t('create.launch.secretPlaceholder')}
                      options={secretKeys.map((k) => ({ label: k, value: k }))}
                      notFoundContent={t('create.launch.secretEmpty')}
                    />
                  </Form.Item>
                </Col>
                <Col span={2}>
                  <MinusCircleOutlined onClick={() => remove(name)} style={{ fontSize: 18, color: '#999' }} />
                </Col>
              </Row>
            ))}
            <Button
              type="dashed"
              onClick={() => add({ secret_key: undefined })}
              icon={<PlusOutlined />}
              block
            >
              {t('create.launch.secretAdd')}
            </Button>
          </>
        )}
      </Form.List>
    </>
  );
}
