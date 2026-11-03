import { Col, Form, Input, Row } from 'antd';
import { useTranslation } from 'react-i18next';
import LabelsField from '@/shared/ui/LabelsField';

/**
 * 基本信息: 显示名称 + 描述 + 标签。引擎固定 SGLang。
 * 任务名由后端在创建时派生 (display_name + 10 位随机), 故 display_name 须 DNS 合法。
 */
export default function BasicSection() {
  const { t } = useTranslation(['inference', 'common']);
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
            { min: 3, max: 29, message: t('create.basic.displayNameLength') },
            {
              // 与后端 InferenceCreate.display_name 的 pattern 逐字符一致 (判定权在
              // 后端, 这里只做即时提示); 由 scripts/check-validation-sync.mjs 防漂移。
              pattern: /^[a-z][a-z0-9-]{1,27}[a-z0-9]$/,
              message: t('create.basic.displayNamePattern'),
            },
          ]}
        >
          <Input maxLength={29} showCount placeholder={t('create.basic.displayNamePlaceholder')} />
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
