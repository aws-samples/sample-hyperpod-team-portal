import { Card, Col, Form, Radio, Row, Typography } from 'antd';
import { useTranslation } from 'react-i18next';
import type { TemplateInfo } from '../../api/types';

interface Props {
  templates: TemplateInfo[];
  selectedTemplateName: string | undefined;
}

/**
 * 模板选择：每个 template 一张 Card，高亮当前选中。
 */
export default function TemplateSection({ templates, selectedTemplateName }: Props) {
  const { t } = useTranslation('devinstance');
  return (
    <Form.Item name="template_name" label={t('create.template.label')} rules={[{ required: true }]}>
      <Radio.Group style={{ width: '100%' }}>
        <Row gutter={[16, 16]}>
          {templates.map((tpl) => (
            <Col span={12} key={tpl.name}>
              <Radio value={tpl.name} style={{ width: '100%' }}>
                <Card
                  size="small"
                  title={tpl.display_name}
                  style={{
                    borderColor:
                      selectedTemplateName === tpl.name ? '#1677ff' : undefined,
                  }}
                >
                  <Typography.Paragraph
                    type="secondary"
                    style={{ fontSize: 12, marginBottom: 4 }}
                  >
                    appType: {tpl.app_type}
                  </Typography.Paragraph>
                  <Typography.Paragraph
                    style={{ fontSize: 12, marginBottom: 0 }}
                  >
                    {tpl.description || '—'}
                  </Typography.Paragraph>
                </Card>
              </Radio>
            </Col>
          ))}
        </Row>
      </Radio.Group>
    </Form.Item>
  );
}
