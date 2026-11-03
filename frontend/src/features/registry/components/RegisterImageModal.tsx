import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Checkbox,
  Empty,
  Input,
  Modal,
  Segmented,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import {
  listEcrRepos,
  listEcrTags,
  registerWorkspaceImage,
  type EcrTag,
} from '@/api/registry';
import { ApiError } from '@/shared/api';

dayjs.extend(relativeTime); // tag 列表用 fromNow() 显示推送时间
import { imageUseLabel, type ImageUse } from '../mock';

const { Text } = Typography;

const USE_VALUES: ImageUse[] = ['dev', 'training', 'inference'];

interface Props {
  wsId: string;
  open: boolean;
  onClose: () => void;
  /** 注册成功回调 (刷新列表)。 */
  onRegistered: () => void;
}

/**
 * 从 ECR 注册镜像弹窗。
 * repo/tag 列表走真实后端 (listEcrRepos / listEcrTags); 注册落 DDB (registerWorkspaceImage)。
 * 支持: repo 选择 → tag 过滤 + 批量勾选 → 用途多选 → 显示名(选填)。
 */
type Mode = 'ecr' | 'manual';

export default function RegisterImageModal({ wsId, open, onClose, onRegistered }: Props) {
  const { t } = useTranslation(['registry', 'common']);
  const useOptions = USE_VALUES.map((v) => ({ value: v, label: imageUseLabel(v) }));
  // 注册方式: 从本账号 ECR 选 / 手动填完整 URI (官方镜像 DLC/SageMaker/public 等)
  const [mode, setMode] = useState<Mode>('ecr');
  const [repos, setRepos] = useState<{ name: string; uri: string }[]>([]);
  const [loadingRepos, setLoadingRepos] = useState(false);
  const [repo, setRepo] = useState<string | undefined>();
  const [submitting, setSubmitting] = useState(false);

  const [tags, setTags] = useState<EcrTag[]>([]);
  const [loadingTags, setLoadingTags] = useState(false);
  const [tagFilter, setTagFilter] = useState('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);

  // 手动模式: 直接粘贴完整镜像 URI (含 tag)
  const [manualUri, setManualUri] = useState('');

  const [uses, setUses] = useState<ImageUse[]>(['dev', 'training']);
  const [displayName, setDisplayName] = useState('');

  // 打开时拉 repo 列表
  useEffect(() => {
    if (!open) return;
    setLoadingRepos(true);
    listEcrRepos()
      .then((rs) => setRepos(rs.map((r) => ({ name: r.name, uri: r.uri }))))
      .catch(() => setRepos([]))
      .finally(() => setLoadingRepos(false));
  }, [open]);

  // 选 repo 后拉 tag 列表
  useEffect(() => {
    if (!repo) {
      setTags([]);
      return;
    }
    setLoadingTags(true);
    setSelectedTags([]);
    listEcrTags(repo)
      .then(setTags)
      .catch(() => setTags([]))
      .finally(() => setLoadingTags(false));
  }, [repo]);

  const repoUri = useMemo(
    () => repos.find((r) => r.name === repo)?.uri ?? '',
    [repos, repo],
  );

  const filteredTags = useMemo(
    () =>
      tags.filter((tg) =>
        tagFilter ? tg.tag.toLowerCase().includes(tagFilter.toLowerCase()) : true,
      ),
    [tags, tagFilter],
  );

  const reset = () => {
    setMode('ecr');
    setRepo(undefined);
    setTags([]);
    setTagFilter('');
    setSelectedTags([]);
    setManualUri('');
    setUses(['dev', 'training']);
    setDisplayName('');
  };

  const handleOk = async () => {
    if (uses.length === 0) {
      message.warning(t('register.atLeastOneUse'));
      return;
    }
    setSubmitting(true);
    try {
      if (mode === 'manual') {
        const uri = manualUri.trim();
        if (!uri) {
          message.warning(t('register.uriRequired'));
          setSubmitting(false);
          return;
        }
        await registerWorkspaceImage(wsId, {
          image_uri: uri,
          display_name: displayName.trim() || undefined,
          uses,
          source: uri.startsWith('public.ecr.aws') ? 'ecr-public' : 'ecr-private',
        });
        message.success(t('register.registered'));
      } else {
        if (!repo || selectedTags.length === 0) {
          message.warning(t('register.pickRepoAndTag'));
          setSubmitting(false);
          return;
        }
        const source = repoUri.startsWith('public.ecr.aws')
          ? 'ecr-public'
          : 'ecr-private';
        // 批量注册: 每个勾选的 tag 注册一条 (串行, 数量通常个位数)。
        for (const tag of selectedTags) {
          const uri = `${repoUri}:${tag}`;
          await registerWorkspaceImage(wsId, {
            image_uri: uri,
            display_name:
              selectedTags.length === 1 && displayName.trim()
                ? displayName.trim()
                : undefined,
            uses,
            source,
          });
        }
        message.success(t('register.registeredCount', { count: selectedTags.length }));
      }
      onRegistered();
      reset();
      onClose();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : t('register.failed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title={t('register.title')}
      open={open}
      onCancel={() => {
        reset();
        onClose();
      }}
      onOk={handleOk}
      okText={t('register.okText')}
      cancelText={t('common:actions.cancel')}
      confirmLoading={submitting}
      width={640}
      destroyOnClose
    >
      <Space direction="vertical" size={18} style={{ width: '100%', marginTop: 8 }}>
        {/* 注册方式切换 */}
        <Segmented<Mode>
          block
          value={mode}
          onChange={setMode}
          options={[
            { label: t('register.modeEcr'), value: 'ecr' },
            { label: t('register.modeManual'), value: 'manual' },
          ]}
        />

        {/* 手动模式: 直接填完整 URI */}
        {mode === 'manual' && (
          <div>
            <Text strong>{t('register.fullUri')}</Text>
            <Input
              style={{ marginTop: 8 }}
              placeholder={t('register.uriPlaceholder')}
              value={manualUri}
              onChange={(e) => setManualUri(e.target.value)}
            />
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 6 }}>
              {t('register.uriHelp')}
            </Text>
          </div>
        )}

        {/* 1. 选仓库 (仅 ECR 模式) */}
        {mode === 'ecr' && (
        <div>
          <Text strong>{t('register.step1')}</Text>
          <Select
            showSearch
            style={{ width: '100%', marginTop: 8 }}
            placeholder={t('register.repoPlaceholder')}
            loading={loadingRepos}
            value={repo}
            onChange={setRepo}
            options={repos.map((r) => ({ label: r.name, value: r.name }))}
            notFoundContent={loadingRepos ? <Spin size="small" /> : t('register.noRepos')}
          />
        </div>
        )}

        {/* 2. 选 tag (过滤 + 批量勾选; 仅 ECR 模式) */}
        {mode === 'ecr' && (
        <div>
          <Text strong>{t('register.step2')}</Text>
          <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
            {t('register.multiHint')}
          </Text>
          <Input
            allowClear
            style={{ marginTop: 8, marginBottom: 8 }}
            placeholder={t('register.tagFilterPlaceholder')}
            value={tagFilter}
            onChange={(e) => setTagFilter(e.target.value)}
            disabled={!repo}
          />
          <div
            style={{
              border: '1px solid #f0f0f0',
              borderRadius: 6,
              maxHeight: 220,
              overflowY: 'auto',
              padding: filteredTags.length ? 4 : 0,
            }}
          >
            {loadingTags ? (
              <div style={{ padding: 24, textAlign: 'center' }}>
                <Spin size="small" />
              </div>
            ) : !repo ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t('register.pickRepoFirst')}
                style={{ margin: '16px 0' }}
              />
            ) : filteredTags.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t('register.noMatchingTag')}
                style={{ margin: '16px 0' }}
              />
            ) : (
              <Checkbox.Group
                style={{ width: '100%' }}
                value={selectedTags}
                onChange={(v) => setSelectedTags(v as string[])}
              >
                {filteredTags.map((tg) => (
                  <div
                    key={tg.tag}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '6px 8px',
                      borderRadius: 4,
                    }}
                  >
                    <Checkbox value={tg.tag}>
                      <Text style={{ fontFamily: 'monospace' }}>{tg.tag}</Text>
                    </Checkbox>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {tg.pushed_at_iso ? dayjs(tg.pushed_at_iso).fromNow() : '—'}
                      {' · '}
                      {tg.size_mb ? `${(tg.size_mb / 1024).toFixed(1)}GB` : '—'}
                    </Text>
                  </div>
                ))}
              </Checkbox.Group>
            )}
          </div>
        </div>
        )}

        {/* 用途多选 (两种模式共用) */}
        <div>
          <Text strong>{t('register.uses')}</Text>
          <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
            {t('register.usesHint')}
          </Text>
          <div style={{ marginTop: 8 }}>
            <Checkbox.Group
              options={useOptions}
              value={uses}
              onChange={(v) => setUses(v as ImageUse[])}
            />
          </div>
        </div>

        {/* 显示名 (选填; ECR 批量选多个 tag 时忽略, 用各自 tag 名) */}
        <div>
          <Text strong>{t('register.displayName')}</Text>
          <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
            {mode === 'ecr' && selectedTags.length > 1
              ? t('register.displayNameHintBatch')
              : t('register.displayNameHint')}
          </Text>
          <Input
            style={{ marginTop: 8 }}
            placeholder={t('register.displayNamePlaceholder')}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            disabled={mode === 'ecr' && selectedTags.length > 1}
          />
        </div>

        {mode === 'ecr' && selectedTags.length > 0 && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('register.willRegister', { count: selectedTags.length })}{' '}
            {uses.map((u) => (
              <Tag key={u} color="blue" style={{ marginInlineEnd: 4 }}>
                {imageUseLabel(u)}
              </Tag>
            ))}
          </Text>
        )}
      </Space>
    </Modal>
  );
}
