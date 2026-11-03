import { theme } from 'antd';

export interface FilterChip<V extends string = string> {
  value: V;
  label: string;
  count?: number;
}

export interface FilterRow<V extends string = string> {
  label: string;
  value: V;
  onChange: (v: V) => void;
  options: FilterChip<V>[];
}

interface Props {
  rows: FilterRow<any>[];
}

// 通用筛选栏: N 行 chip。chip 数量内嵌在标签里, 替代分散的 Tabs+Segmented。
export default function FilterBar({ rows }: Props) {
  const { token } = theme.useToken();
  return (
    <div style={{ marginBottom: 16 }}>
      {rows.map((row) => (
        <div
          key={row.label}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            marginBottom: 8,
            flexWrap: 'wrap',
          }}
        >
          <span
            style={{
              color: token.colorTextSecondary,
              fontSize: 13,
              minWidth: 32,
            }}
          >
            {row.label}
          </span>
          {row.options.map((opt) => {
            const active = opt.value === row.value;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => row.onChange(opt.value)}
                style={{
                  height: 28,
                  padding: '0 12px',
                  borderRadius: 999,
                  border: `1px solid ${active ? token.colorPrimary : token.colorBorderSecondary}`,
                  background: active ? token.colorPrimary : token.colorBgContainer,
                  color: active ? token.colorTextLightSolid : token.colorText,
                  fontSize: 13,
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                  whiteSpace: 'nowrap',
                }}
              >
                {opt.label}
                {typeof opt.count === 'number' && (
                  <span
                    style={{
                      marginLeft: 6,
                      color: active ? token.colorTextLightSolid : token.colorTextTertiary,
                      opacity: active ? 0.8 : 1,
                    }}
                  >
                    {opt.count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
