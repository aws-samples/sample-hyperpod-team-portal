import { Col, Empty, Row, Select, Space, Tag, Tooltip, Typography } from 'antd';
import {
  CloseOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';

/** 统一存储项 (屏蔽开发机/训练数据差异): id 唯一键, path 展示路径。 */
export interface StorageItem {
  id: string;
  path: string;
  access?: 'ro' | 'rw'; // FSx 读写/只读; S3 不传
  isPrimary?: boolean; // FSx 主盘; S3 不传
}

export interface SharedStoragePickerProps {
  fsxOptions: StorageItem[];
  s3Options: StorageItem[];
  fsxSelected: string[];
  s3Selected: string[];
  onFsxChange: (ids: string[]) => void;
  onS3Change: (ids: string[]) => void;
  loading?: boolean;
  // 传了才在 FSx/S3 下拉框标题行右侧显示刷新按钮 (在别处新授权/挂载后即时可选)。
  onReload?: () => void;
}

/** FSx 项标签 (主 / 读写只读); S3 项只有只读。 */
function itemTags(t: TFunction<'common'>, it: StorageItem, kind: 'fsx' | 's3') {
  return (
    <>
      {it.isPrimary && (
        <Tag color="purple" style={{ marginInlineEnd: 4 }}>
          {t('storagePicker.primary')}
        </Tag>
      )}
      {kind === 'fsx' ? (
        <Tag
          color={it.access === 'rw' ? 'gold' : 'default'}
          style={{ marginInlineEnd: 4 }}
        >
          {it.access === 'rw' ? t('storagePicker.readWrite') : t('storagePicker.readOnly')}
        </Tag>
      ) : (
        <Tag style={{ marginInlineEnd: 4 }}>{t('storagePicker.readOnly')}</Tag>
      )}
    </>
  );
}

/**
 * 共享存储: FSx/S3 左右两列多选 + 下方两栏 review。纯 UI, 不碰提交逻辑。
 * 开发机/训练把各自数据 adapt 成 StorageItem 后复用。
 */
export default function SharedStoragePicker({
  fsxOptions,
  s3Options,
  fsxSelected,
  s3Selected,
  onFsxChange,
  onS3Change,
  loading,
  onReload,
}: SharedStoragePickerProps) {
  const { t } = useTranslation('common');
  // FSx/S3 标题行共用的刷新图标, 靠右; 未传 onReload 则不渲染。
  const reloadIcon = onReload ? (
    <Tooltip title={t('actions.refresh')}>
      <ReloadOutlined
        spin={loading}
        onClick={onReload}
        style={{
          color: '#999',
          fontSize: 13,
          cursor: 'pointer',
          marginLeft: 'auto',
          fontWeight: 'normal',
        }}
      />
    </Tooltip>
  ) : null;
  const totalSelected = fsxSelected.length + s3Selected.length;
  const allEmpty = !loading && fsxOptions.length === 0 && s3Options.length === 0;

  if (allEmpty) {
    return (
      <Empty
        description={
          <span style={{ fontSize: 12 }}>
            {t('storagePicker.empty')}
          </span>
        }
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    );
  }

  const renderOptions = (opts: StorageItem[]) =>
    opts.map((it) => ({ value: it.id, label: it.path, item: it }));

  const optionRender =
    (kind: 'fsx' | 's3') =>
    (opt: { data: unknown }) => {
      const it = (opt.data as { item: StorageItem }).item;
      return (
        <Space size={0}>
          {itemTags(t, it, kind)}
          <Typography.Text style={{ fontSize: 13 }}>{it.path}</Typography.Text>
        </Space>
      );
    };

  const reviewColumn = (
    kind: 'fsx' | 's3',
    options: StorageItem[],
    selected: string[],
    onChange: (ids: string[]) => void,
    title: string,
  ) => (
    <div style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 10 }}>
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: kind === 'fsx' ? '#0958d9' : '#389e0d',
          marginBottom: 8,
          borderBottom: '1px solid #f0f0f0',
          paddingBottom: 6,
        }}
      >
        {t('storagePicker.reviewTitle', { title, count: selected.length })}
      </div>
      {selected.length === 0 ? (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {t('storagePicker.noneSelected', { kind: kind === 'fsx' ? 'FSx' : 'S3' })}
        </Typography.Text>
      ) : (
        selected.map((id) => {
          const it = options.find((o) => o.id === id);
          if (!it) return null;
          return (
            <div
              key={id}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '6px 0',
                borderBottom: '1px solid #fafafa',
              }}
            >
              <span style={{ fontSize: 13 }}>
                {itemTags(t, it, kind)}
                {it.path}
              </span>
              <CloseOutlined
                style={{ color: '#f5222d', cursor: 'pointer', fontSize: 12 }}
                onClick={() => onChange(selected.filter((x) => x !== id))}
              />
            </div>
          );
        })
      )}
    </div>
  );

  return (
    <>
      {/* 选择区: FSx(左) / S3(右) */}
      <Row gutter={12} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <div
            style={{
              border: '1px solid #d9e7ff',
              background: '#f5f9ff',
              borderRadius: 6,
              padding: 10,
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                fontSize: 12,
                color: '#0958d9',
                fontWeight: 600,
                marginBottom: 6,
              }}
            >
              {t('storagePicker.fsxTitle')}
              <Tooltip title={t('storagePicker.fsxHelp')}>
                <QuestionCircleOutlined
                  style={{ color: '#999', marginLeft: 6, cursor: 'help', fontWeight: 'normal' }}
                />
              </Tooltip>
              {reloadIcon}
            </div>
            <Select
              mode="multiple"
              style={{ width: '100%', fontSize: 13 }}
              placeholder={t('storagePicker.fsxPlaceholder')}
              loading={loading}
              value={fsxSelected}
              onChange={onFsxChange}
              showSearch
              optionFilterProp="label"
              options={renderOptions(fsxOptions)}
              optionRender={optionRender('fsx')}
            />
          </div>
        </Col>
        <Col span={12}>
          <div
            style={{
              border: '1px solid #d9f0e0',
              background: '#f6fff9',
              borderRadius: 6,
              padding: 10,
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                fontSize: 12,
                color: '#389e0d',
                fontWeight: 600,
                marginBottom: 6,
              }}
            >
              {t('storagePicker.s3Title')}
              {reloadIcon}
            </div>
            <Select
              mode="multiple"
              style={{ width: '100%', fontSize: 13 }}
              placeholder={t('storagePicker.s3Placeholder')}
              loading={loading}
              value={s3Selected}
              onChange={onS3Change}
              showSearch
              optionFilterProp="label"
              options={renderOptions(s3Options)}
              optionRender={optionRender('s3')}
            />
          </div>
        </Col>
      </Row>

      {/* Review 区: 已选挂载, 左右两栏 */}
      <div
        style={{ fontSize: 13, color: '#666', fontWeight: 600, marginBottom: 8 }}
      >
        {t('storagePicker.selectedTotal', { total: totalSelected })}
      </div>
      <Row gutter={12}>
        <Col span={12}>
          {reviewColumn('fsx', fsxOptions, fsxSelected, onFsxChange, 'FSx')}
        </Col>
        <Col span={12}>
          {reviewColumn('s3', s3Options, s3Selected, onS3Change, 'S3')}
        </Col>
      </Row>
    </>
  );
}
