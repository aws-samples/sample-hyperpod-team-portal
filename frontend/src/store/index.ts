import { create } from 'zustand';
import type { User } from '@/types';

export type ThemeMode = 'light' | 'dark';

interface AppState {
  currentWorkspaceId: string;
  /** 登录用户. AuthGate 拿到 /api/v1/users/me 后通过 setCurrentUser 注入. */
  currentUser: User | null;
  themeMode: ThemeMode;
  setCurrentWorkspaceId: (id: string) => void;
  setCurrentUser: (user: User | null) => void;
  toggleTheme: () => void;
  setThemeMode: (mode: ThemeMode) => void;
}

// M1: 默认空,由 WorkspaceList / 路由进入某 workspace 后由 MainLayout 自动塞真实 UUID
// 不再 fallback 到 mock ws-001(会触发后端 UUID 422)
export const useAppStore = create<AppState>((set) => ({
  currentWorkspaceId: '',
  currentUser: null,
  themeMode: 'light',
  setCurrentWorkspaceId: (id) => set({ currentWorkspaceId: id }),
  setCurrentUser: (user) => set({ currentUser: user }),
  toggleTheme: () =>
    set((s) => ({ themeMode: s.themeMode === 'light' ? 'dark' : 'light' })),
  setThemeMode: (mode) => set({ themeMode: mode }),
}));
