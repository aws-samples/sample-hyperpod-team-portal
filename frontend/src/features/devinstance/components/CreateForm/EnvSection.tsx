import { Button, Input, Space } from 'antd';
import { useTranslation } from 'react-i18next';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';

export interface EnvRow {
  key: string;
  value: string;
}

interface Props {
  envRows: EnvRow[];
  onChange: (rows: EnvRow[]) => void;
}

/**
 * 环境变量：KV 行编辑。空 key 行在提交时会被过滤。
 *
 * 受控组件 · envRows 状态在父页。
 */
export default function EnvSection({ envRows, onChange }: Props) {
  const { t } = useTranslation('devinstance');
  const addRow = () => onChange([...envRows, { key: '', value: '' }]);
  const removeRow = (idx: number) =>
    onChange(envRows.filter((_, i) => i !== idx));
  const updateRow = (idx: number, patch: Partial<EnvRow>) =>
    onChange(envRows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));

  return (
    <>
      {envRows.map((row, idx) => (
        <Space
          key={idx}
          style={{ display: 'flex', marginBottom: 8 }}
          align="baseline"
        >
          <Input
            placeholder="KEY"
            value={row.key}
            style={{ width: 220 }}
            onChange={(e) => updateRow(idx, { key: e.target.value })}
          />
          <Input
            placeholder="VALUE"
            value={row.value}
            style={{ width: 320 }}
            onChange={(e) => updateRow(idx, { value: e.target.value })}
          />
          <Button
            type="text"
            danger
            icon={<DeleteOutlined />}
            onClick={() => removeRow(idx)}
          />
        </Space>
      ))}
      <Button type="dashed" icon={<PlusOutlined />} onClick={addRow} block>
        {t('create.env.add')}
      </Button>
    </>
  );
}
