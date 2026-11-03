import { Navigate, useRoutes } from 'react-router-dom';
import MainLayout from '@/layouts/MainLayout';
import Login from '@/pages/Login';
import { AuthGate, Callback as AuthCallback } from '@/features/auth';
import { WorkspaceList, WorkspaceDashboard } from '@/features/workspace';
import { DevList, DevDetail, DevInstanceCreate } from '@/features/devinstance';
import { TrainingList, TrainingCreate, TrainingDetail } from '@/features/training';
import { InferenceList, InferenceCreate, InferenceDetail } from '@/features/inference';
import { DynamoList, DynamoCreate, DynamoDetail } from '@/features/dynamo';
import { RayJobList, RayJobCreate, RayJobDetail } from '@/features/rayjob';
import { LlmdList, LlmdCreate, LlmdDetail } from '@/features/llmd';
import { TasksOverview } from '@/features/tasks';
import ImageHub from '@/features/registry/pages/ImageHub';
import TokenHub from '@/features/secret/pages/TokenHub';
import {
  AdminResourceTemplates,
  AdminPriorityLabels,
  AdminWorkspacePreemption,
} from '@/features/admin';
// 临时 demo 路由: FSx 目录配额 UI (UI 预览, 未接后端)
import FsxDirQuotaDemo from '@/features/admin/pages/FsxDirQuotaDemo';
// 监控 (所有用户可看, 与 ws 无关)
import MonitoringFsx from '@/features/monitoring/pages/MonitoringFsx';
import MonitoringKueue from '@/features/monitoring/pages/MonitoringKueue';
import {
  DocsOverview,
  DocsWorkspace,
  DocsPermissions,
  DocsDevInstance,
  DocsTraining,
  DocsInference,
  DocsLlmd,
  DocsQuota,
  DocsRegistry,
  DocsSharing,
  DocsSecret,
  DocsObservability,
  DocsArchitecture,
  DocsFaq,
  DocsGpuFaultRunbook,
} from '@/features/docs';
import { useAppStore } from '@/store';

function DefaultRedirect() {
  const wsId = useAppStore((s) => s.currentWorkspaceId);
  return <Navigate to={`/workspaces/${wsId}`} replace />;
}

// 旧 /admin/resource-templates (无 wsId) → 新的 ws 级路径; 无当前 ws 则回工作空间列表。
function ResourceTemplatesRedirect() {
  const wsId = useAppStore((s) => s.currentWorkspaceId);
  return (
    <Navigate
      to={wsId ? `/workspaces/${wsId}/resource-templates` : '/workspaces'}
      replace
    />
  );
}

export default function AppRouter() {
  const element = useRoutes([
    { path: '/', element: <DefaultRedirect /> },
    { path: '/login', element: <Login /> },
    // OIDC PKCE flow callback · Cognito 跳回此路径换 token
    // 不能放进 AuthGate 包裹的 MainLayout 里 (callback 时还没登录, 进 AuthGate 会死循环)
    { path: '/auth/callback', element: <AuthCallback /> },
    {
      path: '/',
      element: (
        <AuthGate>
          <MainLayout />
        </AuthGate>
      ),
      children: [
        { path: 'workspaces', element: <WorkspaceList /> },
        { path: 'workspaces/:wsId', element: <WorkspaceDashboard /> },
        // Workspace-scoped task aggregator (Stage 5-C).
        { path: 'workspaces/:wsId/tasks', element: <TasksOverview /> },
        { path: 'workspaces/:wsId/dev', element: <DevList /> },
        { path: 'workspaces/:wsId/dev/new', element: <DevInstanceCreate /> },
        { path: 'workspaces/:wsId/dev/:id', element: <DevDetail /> },
        { path: 'workspaces/:wsId/training', element: <TrainingList /> },
        { path: 'workspaces/:wsId/training/new', element: <TrainingCreate /> },
        { path: 'workspaces/:wsId/training/:id', element: <TrainingDetail /> },
        { path: 'workspaces/:wsId/inference', element: <InferenceList /> },
        { path: 'workspaces/:wsId/inference/new', element: <InferenceCreate /> },
        { path: 'workspaces/:wsId/inference/:id', element: <InferenceDetail /> },
        { path: 'workspaces/:wsId/dynamo', element: <DynamoList /> },
        { path: 'workspaces/:wsId/dynamo/new', element: <DynamoCreate /> },
        { path: 'workspaces/:wsId/dynamo/:id', element: <DynamoDetail /> },
        { path: 'workspaces/:wsId/rayjob', element: <RayJobList /> },
        { path: 'workspaces/:wsId/rayjob/new', element: <RayJobCreate /> },
        { path: 'workspaces/:wsId/rayjob/:id', element: <RayJobDetail /> },
        { path: 'workspaces/:wsId/llmd', element: <LlmdList /> },
        { path: 'workspaces/:wsId/llmd/new', element: <LlmdCreate /> },
        { path: 'workspaces/:wsId/llmd/:id', element: <LlmdDetail /> },
        // 资源模版: workspace 级 (按 ws 维护), 路由带 wsId; 任何 ws 成员可见 (只读)。
        { path: 'workspaces/:wsId/resource-templates', element: <AdminResourceTemplates /> },
        // 镜像中心: workspace 级 (DEMO), 管理本 ws 可用镜像。
        { path: 'workspaces/:wsId/images', element: <ImageHub /> },
        // Token 导入: workspace 级, 每人管自己的 GitHub token。
        { path: 'workspaces/:wsId/tokens', element: <TokenHub /> },
        // 监控 (所有登录用户可看, 与工作空间无关)
        { path: 'monitoring/fsx', element: <MonitoringFsx /> },
        { path: 'monitoring/kueue', element: <MonitoringKueue /> },
        // 平台级管理路由 (仅平台超管)
        // FSx 目录配额管理 (平台超管)
        { path: 'admin/fsx-quota', element: <FsxDirQuotaDemo /> },
        // 旧 demo 路径重定向, 防外链 404
        { path: 'admin/fsx-quota-demo', element: <Navigate to="/admin/fsx-quota" replace /> },
        { path: 'admin/priority-labels', element: <AdminPriorityLabels /> },
        { path: 'admin/preemption', element: <AdminWorkspacePreemption /> },
        // 旧资源模版路由 (无 wsId): 重定向到当前 ws 下的新路径。
        { path: 'admin/resource-templates', element: <ResourceTemplatesRedirect /> },
        // 其他旧管理路由 → 重定向到优先级档位, 防外链 404。
        { path: 'admin/*', element: <Navigate to="/admin/priority-labels" replace /> },
        // Docs routes — 静态产品文档, 不需要 wsId。
        { path: 'docs', element: <DocsOverview /> },
        { path: 'docs/overview', element: <DocsOverview /> },
        { path: 'docs/workspace', element: <DocsWorkspace /> },
        { path: 'docs/permissions', element: <DocsPermissions /> },
        { path: 'docs/devinstance', element: <DocsDevInstance /> },
        { path: 'docs/training', element: <DocsTraining /> },
        { path: 'docs/inference', element: <DocsInference /> },
        { path: 'docs/llmd', element: <DocsLlmd /> },
        { path: 'docs/registry', element: <DocsRegistry /> },
        { path: 'docs/sharing', element: <DocsSharing /> },
        { path: 'docs/secret', element: <DocsSecret /> },
        { path: 'docs/quota', element: <DocsQuota /> },
        { path: 'docs/observability', element: <DocsObservability /> },
        { path: 'docs/architecture', element: <DocsArchitecture /> },
        { path: 'docs/faq', element: <DocsFaq /> },
        { path: 'docs/gpu-fault-runbook', element: <DocsGpuFaultRunbook /> },
        // Docs 兜底 — 不识别的子路径回概览, 防外链 404。
        { path: 'docs/*', element: <Navigate to="/docs" replace /> },
      ],
    },
    { path: '*', element: <DefaultRedirect /> },
  ]);
  return element;
}
