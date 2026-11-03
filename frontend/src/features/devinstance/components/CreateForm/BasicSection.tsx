import { Form, Input } from 'antd';
import { useTranslation } from 'react-i18next';

const NAME_PATTERN = /^[a-z][a-z0-9-]{2,62}$/;

/**
 * 基本信息：DNS-label name、显示名、描述。
 *
 * DNS label 规则来自 K8s CR name 约束（小写开头 3-63 字符）。
 */
export default function BasicSection() {
  const { t } = useTranslation(['devinstance', 'common']);
  return (
    <>
      <Form.Item
        name="name"
        label={t('create.basic.nameLabel')}
        rules={[
          { required: true, message: t('create.basic.nameRequired') },
          {
            pattern: NAME_PATTERN,
            message: t('create.basic.namePattern'),
          },
        ]}
      >
        <Input placeholder="my-dev-01" />
      </Form.Item>
      <Form.Item
        name="display_name"
        label={t('create.basic.displayNameLabel')}
        rules={[{ required: true, message: t('create.basic.displayNameRequired') }]}
      >
        <Input placeholder={t('create.basic.displayNamePlaceholder')} />
      </Form.Item>
      <Form.Item name="description" label={t('common:fields.description')}>
        <Input placeholder={t('create.basic.descriptionPlaceholder')} />
      </Form.Item>
    </>
  );
}
