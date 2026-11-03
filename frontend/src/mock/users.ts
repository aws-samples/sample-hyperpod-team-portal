/**
 * Mock 用户列表 — 仅供仍依赖假数据的页面使用 (Storage 授权对话框、
 * Dashboard 成员条形图、infra/devInstances/trainingJobs 假 creator).
 *
 * 真正的"当前登录用户"走 Zustand `currentUser` (类型 `User`,
 * 由 AuthGate 从 `/api/v1/users/me` 注入). 改 `User` 类型时 mock 不要
 * 跟着改 — 把这些 mock 模块逐个迁到真接口才是清理路径.
 */

export type MockUserRole = 'admin' | 'user' | 'viewer';

export interface MockUser {
  id: string;
  email: string;
  displayName: string;
  role: MockUserRole;
}

export const mockUsers: MockUser[] = [
  { id: 'u-001', email: 'alice@example.com', displayName: 'Alice Chen', role: 'admin' },
  { id: 'u-002', email: 'bob@example.com', displayName: 'Bob Wang', role: 'user' },
  { id: 'u-003', email: 'carol@example.com', displayName: 'Carol Li', role: 'user' },
  { id: 'u-004', email: 'david@example.com', displayName: 'David Zhao', role: 'user' },
  { id: 'u-005', email: 'eve@example.com', displayName: 'Eve Liu', role: 'user' },
  { id: 'u-006', email: 'frank@example.com', displayName: 'Frank Xu', role: 'user' },
  { id: 'u-007', email: 'grace@example.com', displayName: 'Grace Sun', role: 'user' },
  { id: 'u-008', email: 'henry@example.com', displayName: 'Henry Zhou', role: 'viewer' },
  { id: 'u-009', email: 'ivy@example.com', displayName: 'Ivy Wu', role: 'viewer' },
  { id: 'u-010', email: 'jack@example.com', displayName: 'Jack Ma', role: 'user' },
];
