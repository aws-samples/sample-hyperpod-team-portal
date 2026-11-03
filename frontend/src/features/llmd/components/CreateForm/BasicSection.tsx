import { Col, Form, Input, Row } from 'antd';
import { useTranslation } from 'react-i18next';
import LabelsField from '@/shared/ui/LabelsField';

/**
 * 基本信息: 显示名称 + 描述 + 标签。
 * 任务名由后端在创建时派生 (display_name + 10 位随机), 故 display_name 须 DNS 合法。
 * 上限 20 而非 29: Kueue 的 pod-group-name label 里嵌了任务名 (见 core/naming.py)。
 */
export default function BasicSection() {
  const { t } = useTranslation(['llmd', 'common']);
  return (
    <Row gutter={16}>
      <Col span={12}>
        <Form.Item
          name="display_name"
          label={t('create.basic.displayNameLabel')}
          tooltip={t('create.basic.displayNameTooltip')}
          rules={[
            { required: true, message: t('create.basic.displayNameRequired') },
            // 用 validator 不用第二条正则: check-validation-sync.mjs 要求本文件只有一条
            {
              validator: (_, v: string) =>
                !v || /^[\x20-\x7E]*$/.test(v)
                  ? Promise.resolve()
                  : Promise.reject(
                      new Error(t('create.basic.displayNameAscii')),
                    ),
            },
            { min: 3, max: 20, message: t('create.basic.displayNameLength') },
            {
              // 与后端 LlmdCreate.display_name 逐字符一致 (判定权在后端)
              pattern: /^[a-z][a-z0-9-]{1,18}[a-z0-9]$/,
              message: t('create.basic.displayNamePattern'),
            },
          ]}
        >
          <Input maxLength={20} showCount placeholder={t('create.basic.displayNamePlaceholder')} />
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
