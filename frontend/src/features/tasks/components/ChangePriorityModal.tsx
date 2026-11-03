import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { App, Modal, Select } from 'antd';
// 复用 priority 模块 client (后端: patch CR label + delete Workload 重建)
import { listPriorityClasses, patchTaskPriority } from '@/api/priority';
import type { PriorityClassItem } from '@/api/priority';
import type { TaskRow } from '../api';

interface Props {
  wsId: string;
  task: TaskRow | null; // null = 关闭
  onClose: () => void;
  onSuccess: () => void; // patch 成功回调 (触发延迟重拉)
}

export default function ChangePriorityModal({ wsId, task, onClose, onSuccess }: Props) {
  const { t } = useTranslation('tasks');
  const { message } = App.useApp();
  const [options, setOptions] = useState<PriorityClassItem[]>([]);
  const [value, setValue] = useState<string | undefined>();
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!task) return;
    setValue(task.priority_class ?? undefined);
    listPriorityClasses()
      .then(setOptions)
      .catch((e) => message.error(t('changePriority.loadFailed', { error: String(e) })));
  }, [task, message, t]);

  const handleOk = async () => {
    if (!task || !value) return;
    if (!task.k8s_name) {
      message.error(t('changePriority.missingCrName'));
      return;
    }
    setSubmitting(true);
    try {
      // 按 (task_type, cr_name=k8s_name) 反查 Workload → patch label + 删 Workload 重建
      await patchTaskPriority(wsId, task.kind, task.k8s_name, value);
      message.success(t('changePriority.success'));
      onSuccess();
      onClose();
    } catch (e) {
      message.error(t('changePriority.failed', { error: String(e) })); // 400/403/404/409/502 后端文案
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={!!task}
      title={t('changePriority.title', { name: task?.name ?? '' })}
      onOk={handleOk}
      onCancel={onClose}
      confirmLoading={submitting}
      okButtonProps={{ disabled: !value }}
    >
      <Select
        style={{ width: '100%' }}
        placeholder={t('changePriority.placeholder')}
        value={value}
        onChange={setValue}
        options={options.map((o) => ({
          label: o.value != null ? `${o.name} (${o.value})` : o.name,
          value: o.name,
        }))}
      />
    </Modal>
  );
}
