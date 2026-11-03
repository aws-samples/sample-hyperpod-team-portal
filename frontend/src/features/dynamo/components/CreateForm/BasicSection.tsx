import { useEffect, useRef } from 'react';
import { Col, Form, Input, Row } from 'antd';
import { useTranslation } from 'react-i18next';
import LabelsField from '@/shared/ui/LabelsField';
import { randomSuffix, toDnsLabel } from '@/shared/taskName';

/**
 * 基本信息: 显示名称 + 任务名 (= sanitize(显示名) + 10 随机后缀, 即最终 k8s 名, 只读)。
 * 任务名由显示名派生 (useWatch): 显示名变只换前缀, 随机后缀本页挂载固定一次不变。
 * 新建/克隆统一走这条派生 (克隆预填 display_name 也会触发), 保证唯一且不重掷随机。(照推理 BasicSection)
 */
export default function BasicSection() {
  const { t } = useTranslation(['dynamo', 'common']);
  const form = Form.useFormInstance();
  const suffix = useRef(randomSuffix()); // 本页挂载定一次; 克隆是新页面挂载 → 新随机, 唯一
  const displayName = Form.useWatch('display_name', form) as string | undefined;
  useEffect(() => {
    const prefix = toDnsLabel(displayName || '');
    form.setFieldValue('name', prefix ? `${prefix}-${suffix.current}` : '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayName]);
  return (
    <Row gutter={16}>
      <Col span={12}>
        <Form.Item
          name="display_name"
          label={t('create.basic.displayNameLabel')}
          tooltip={t('create.basic.displayNameTooltip')}
          rules={[{ required: true, message: t('create.basic.displayNameRequired') }]}
        >
          <Input placeholder={t('create.basic.displayNamePlaceholder')} />
        </Form.Item>
      </Col>
      <Col span={12}>
        <Form.Item
          name="name"
          label={t('create.basic.taskNameLabel')}
          tooltip={t('create.basic.taskNameTooltip')}
          rules={[
            { required: true, message: t('create.basic.taskNameRequired') },
            {
              pattern: /^[a-z][a-z0-9-]{2,62}$/,
              message: t('create.basic.taskNamePattern'),
            },
          ]}
        >
          <Input placeholder={t('create.basic.taskNamePlaceholder')} readOnly />
        </Form.Item>
      </Col>
      <Col span={24}>
        <Form.Item
          name="description"
          label={t('common:fields.description')}
          tooltip={t('create.basic.descriptionTooltip')}
        >
          <Input.TextArea
            rows={2}
            maxLength={512}
            showCount
            placeholder={t('create.basic.descriptionPlaceholder')}
          />
        </Form.Item>
      </Col>
      <Col span={24}>
        <LabelsField />
      </Col>
    </Row>
  );
}
