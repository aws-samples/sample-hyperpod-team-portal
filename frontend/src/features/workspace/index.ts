/**
 * Public exports for the workspace feature. Consumers should import only from
 * this barrel, never reach into `./pages` or `./api` directly.
 */
export { default as WorkspaceList } from './pages/List';
export { default as WorkspaceDashboard } from './pages/Dashboard';

export {
  listWorkspaces,
  getWorkspace,
  createWorkspace,
  updateWorkspace,
  deleteWorkspace,
  listMembers,
  type Workspace,
  type WorkspaceDetail,
  type WorkspaceMember,
  type WorkspaceStatus,
  type WorkspaceRole,
  type WorkspaceCreatePayload,
  type WorkspaceUpdatePayload,
  type ListWorkspacesParams,
  type WorkspaceQuotaResourceRequest,
  type WorkspaceSharingStrategy,
  type WorkspacePreemptPolicy,
} from './api';
