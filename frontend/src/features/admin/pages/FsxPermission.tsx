/**
 * Deprecated shim · use /admin/storage?tab=permission-groups instead.
 *
 * The original 556-line FSx permission UI was merged into Storage.tsx (Tab 2)
 * during the 2026-05-08 3-tab consolidation. This file is kept as a safety net
 * in case any internal link still imports the old component path.
 */
import { Navigate } from 'react-router-dom';

export default function FsxPermission() {
  return <Navigate to="/admin/storage?tab=permission-groups" replace />;
}
