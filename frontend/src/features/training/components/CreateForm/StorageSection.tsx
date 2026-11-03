import SharedStoragePicker, {
  type StorageItem,
} from '@/shared/ui/SharedStoragePicker';
import type { SharedPVCInfo } from '@/features/devinstance/api/client';
import type { WorkspaceS3Mount } from '@/features/workspace/api';

export interface StorageSectionProps {
  sharedPvcs: SharedPVCInfo[] | null;
  fsxChecked: string[];
  onFsxChange: (v: string[]) => void;
  wsS3Mounts: WorkspaceS3Mount[];
  s3Checked: string[];
  onS3Change: (v: string[]) => void;
  onReload?: () => void;
  mountsLoading?: boolean;
}

/**
 * 共享存储 (FSx/S3 分开选 + review): adapt 数据成 StorageItem 后渲染共用组件。
 * FSx id = pvc_name (p.name), S3 id = mount_id; 与 index 的
 * buildFsxRefs/buildS3Datasets 一致, 提交逻辑不变。
 */
export default function StorageSection({
  sharedPvcs,
  fsxChecked,
  onFsxChange,
  wsS3Mounts,
  s3Checked,
  onS3Change,
  onReload,
  mountsLoading,
}: StorageSectionProps) {
  const fsxOptions: StorageItem[] = (sharedPvcs ?? [])
    .filter((p) => p.mount_path)
    .map((p) => ({
      id: p.name,
      path: p.mount_path ?? p.name,
      access: (p.access as 'ro' | 'rw' | undefined) ?? undefined,
      isPrimary: p.is_primary ?? false,
    }));
  const s3Options: StorageItem[] = wsS3Mounts.map((m) => ({
    id: m.mount_id,
    path: m.mount_path,
  }));

  return (
    <SharedStoragePicker
      fsxOptions={fsxOptions}
      s3Options={s3Options}
      fsxSelected={fsxChecked}
      s3Selected={s3Checked}
      onFsxChange={onFsxChange}
      onS3Change={onS3Change}
      loading={sharedPvcs === null || mountsLoading}
      onReload={onReload}
    />
  );
}
