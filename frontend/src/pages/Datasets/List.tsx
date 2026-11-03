/**
 * Deprecated shim · datasets are now a read-only view over permission grants
 * with a `dataset_name` set. Access them via /admin/storage?tab=datasets.
 *
 * The original 294-line per-workspace datasets list (with lineage mock) was
 * retired on 2026-05-08 when storage, permissions, and datasets were merged
 * into a single three-tab page.
 */
import { Navigate } from 'react-router-dom';

export default function DatasetsList() {
  return <Navigate to="/admin/storage?tab=datasets" replace />;
}
