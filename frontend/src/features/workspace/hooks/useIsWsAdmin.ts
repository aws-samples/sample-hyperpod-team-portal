import { useEffect, useState } from 'react';
import { listMembers } from '@/features/workspace/api';
import { useAppStore } from '@/store';

interface WsAdminState {
  /** 超管 OR 当前 ws 的 admin 成员 — 用于 ws 级管理操作/图表的显隐。 */
  canManage: boolean;
  /** 判定中 (查 membership)。超管/无 wsId 时直接 false (无需查)。 */
  loading: boolean;
}

/**
 * 判断当前用户能否"管理"指定 workspace = 平台超管 OR 该 ws 的 admin 成员。
 *
 * 前端没有现成的 ws-admin 布尔 (currentUser.is_admin 只是平台超管, 与具体 ws
 * 无关), 故非超管时拉 listMembers(wsId) 找自己 role==admin。
 *
 * 与后端 assert_ws_admin 同口径。任务总览菜单、ws GPU 图表等"仅管理员可见"
 * 的入口共用本 hook (渲染前判定 → 不闪现)。
 */
export function useIsWsAdmin(wsId: string | undefined): WsAdminState {
  const currentUser = useAppStore((s) => s.currentUser);
  const isSuperAdmin = currentUser?.is_admin === true;
  const myId = currentUser?.id;
  const [isWsAdmin, setIsWsAdmin] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isSuperAdmin || !wsId) {
      setIsWsAdmin(false);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const members = await listMembers(wsId);
        if (cancelled) return;
        const me = members.find((m) => m.user_id === myId);
        setIsWsAdmin(me?.role === 'admin');
      } catch {
        if (!cancelled) setIsWsAdmin(false);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [wsId, isSuperAdmin, myId]);

  return { canManage: isSuperAdmin || isWsAdmin, loading };
}
