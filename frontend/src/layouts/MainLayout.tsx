import { useEffect, useMemo, useState } from 'react';
import { Link, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom';
import { ProLayout } from '@ant-design/pro-components';
import type { MenuDataItem } from '@ant-design/pro-components';
import { Avatar, Select, Tag, Tooltip } from 'antd';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import {
  ApartmentOutlined,
  ApiOutlined,
  AppstoreOutlined,
  BookOutlined,
  CloudServerOutlined,
  CodeOutlined,
  ContainerOutlined,
  ControlOutlined,
  HddOutlined,
  DashboardOutlined,
  HomeOutlined,
  InteractionOutlined,
  KeyOutlined,
  MedicineBoxOutlined,
  QuestionCircleOutlined,
  ReadOutlined,
  RocketOutlined,
  SafetyCertificateOutlined,
  ShareAltOutlined,
  ThunderboltOutlined,
  UnorderedListOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useAppStore } from '@/store';
import { isHiddenFeaturePath } from '@/config/features';
import ApiTokenModal from '@/shared/ui/ApiTokenModal';
import LanguageSwitcher from '@/shared/ui/LanguageSwitcher';
import { listMembers, listWorkspaces, type Workspace } from '@/features/workspace/api';
import {
  aggregateQuota,
  getWorkspaceQuota,
  getWorkspaceQuotaUsage,
} from '@/features/quota/api';

/**
 * Resolve the active workspace id — prefer the `:wsId` URL param, fall back to
 * the store so that non-workspace routes still work.
 */
const useActiveWorkspaceId = (): string => {
  const params = useParams();
  const storeWsId = useAppStore((s) => s.currentWorkspaceId);
  return params.wsId ?? storeWsId;
};

// 产品文档子菜单 (新窗口打开 docs 时, 左侧只渲这棵树)。
const buildDocsMenu = (t: TFunction<'layout'>): MenuDataItem[] => [
  { path: '/docs/overview', name: t('docsMenu.overview'), icon: <ReadOutlined /> },
  { path: '/docs/workspace', name: t('docsMenu.workspace'), icon: <HomeOutlined /> },
  { path: '/docs/devinstance', name: t('docsMenu.devinstance'), icon: <CodeOutlined /> },
  { path: '/docs/training', name: t('docsMenu.training'), icon: <ThunderboltOutlined /> },
  { path: '/docs/inference', name: t('docsMenu.inference'), icon: <RocketOutlined /> },
  { path: '/docs/llmd', name: t('docsMenu.llmd'), icon: <RocketOutlined /> },
  { path: '/docs/registry', name: t('docsMenu.registry'), icon: <ContainerOutlined /> },
  { path: '/docs/sharing', name: t('docsMenu.sharing'), icon: <ShareAltOutlined /> },
  { path: '/docs/secret', name: t('docsMenu.secret'), icon: <KeyOutlined /> },
  { path: '/docs/quota', name: t('docsMenu.quota'), icon: <AppstoreOutlined /> },
  { path: '/docs/observability', name: t('docsMenu.observability'), icon: <DashboardOutlined /> },
  { path: '/docs/architecture', name: t('docsMenu.architecture'), icon: <ApartmentOutlined /> },
  { path: '/docs/permissions', name: t('docsMenu.permissions'), icon: <SafetyCertificateOutlined /> },
  { path: '/docs/faq', name: t('docsMenu.faq'), icon: <QuestionCircleOutlined /> },
];

const buildMenu = (
  t: TFunction<'layout'>,
  wsId: string,
  isAdmin: boolean,
  canManage: boolean,
): MenuDataItem[] => {
  // wsId 为空时(刚登陆/在工作空间列表),workspace 子菜单 disabled
  // 引导用户先点"工作空间"选一个,避免后端 UUID 422 + 路径死循环
  // 不再把"(请先选工作空间)"拼进 name (显示不全); 改为 disabled 置灰 + menuItemRender
  // 里给 disabled 项包 Tooltip 提示 (见 ProLayout menuItemRender)。
  const hasWs = Boolean(wsId);
  const wsBase = hasWs ? `/workspaces/${wsId}` : '/workspaces';
  const menus: MenuDataItem[] = [
    {
      path: '/workspaces',
      name: t('menu.workspace'),
      icon: <HomeOutlined />,
    },
    {
      path: `${wsBase}/dev`,
      name: t('menu.devinstance'),
      icon: <CodeOutlined />,
      disabled: !hasWs,
    },
    {
      path: `${wsBase}/training`,
      name: t('menu.training'),
      icon: <ThunderboltOutlined />,
      disabled: !hasWs,
    },
    {
      // Ray 训练 (KubeRay RayJob): 与训练任务并列, 跑 RLHF/超参/数据并行。
      path: `${wsBase}/rayjob`,
      name: t('menu.rayjob'),
      icon: <ApartmentOutlined />,
      disabled: !hasWs,
    },
    {
      path: `${wsBase}/inference`,
      name: t('menu.inference'),
      icon: <RocketOutlined />,
      disabled: !hasWs,
    },
    {
      path: `${wsBase}/llmd`,
      name: t('menu.llmd'),
      icon: <RocketOutlined />,
      disabled: !hasWs,
    },
    {
      path: `${wsBase}/dynamo`,
      name: t('menu.dynamo'),
      icon: <RocketOutlined />,
      disabled: !hasWs,
    },
    // 资源模版是 workspace 级 (按 ws 维护), 故与业务菜单并列、路由带 wsId。
    // 任何 ws 成员可见 (只读); 编辑/删除由页面内 canEdit (ws admin) 控制。
    {
      path: `${wsBase}/resource-templates`,
      name: t('menu.resourceTemplates'),
      icon: <CloudServerOutlined />,
      disabled: !hasWs,
    },
    // 资产管理 (workspace 级折叠组): 镜像 + Github token 都是 ws 级资产。
    // 父项 path='/assets' 只作分组 key (不导航); 未选 ws 时父+子一起 disabled。
    {
      path: '/assets',
      name: t('menu.assets'),
      icon: <AppstoreOutlined />,
      disabled: !hasWs,
      children: [
        // 镜像: 管理本 ws 可用容器镜像 (从 ECR 注册)。
        {
          path: `${wsBase}/images`,
          name: t('menu.images'),
          icon: <ContainerOutlined />,
          disabled: !hasWs,
        },
        // Secret: 每人管自己的通用 key-value Secret, 训练环境变量注入用。
        {
          path: `${wsBase}/tokens`,
          name: 'Secret',
          icon: <KeyOutlined />,
          disabled: !hasWs,
        },
      ],
    },
  ];

  // 管理员区: 普通成员看不到, 折叠子菜单, 与"产品文档"视觉对称。
  // - 任务总览: ws 管理员 / 平台超管可见 (canManage)
  // - 优先级档位 / 工作空间抢占开关: 仅平台超管 (isAdmin)
  if (canManage || isAdmin) {
    const adminChildren: MenuDataItem[] = [];
    if (canManage) {
      adminChildren.push({
        path: `${wsBase}/tasks`,
        name: t('menu.taskOverview'),
        icon: <UnorderedListOutlined />,
        disabled: !hasWs,
      });
    }
    if (isAdmin) {
      adminChildren.push(
        {
          path: '/admin/priority-labels',
          name: t('menu.priorityClass'),
          icon: <ControlOutlined />,
        },
        {
          path: '/admin/preemption',
          name: t('menu.preemption'),
          icon: <InteractionOutlined />,
        },
        {
          // FSx配额 (一级目录配额管理)
          path: '/admin/fsx-quota',
          name: t('menu.fsxQuota'),
          icon: <HddOutlined />,
        },
      );
    }
    menus.push({
      path: '/admin',
      name: t('menu.admin'),
      icon: <SafetyCertificateOutlined />,
      children: adminChildren,
    });
  }

  // 监控: 所有登录用户可见, 与工作空间无关 (选不选 ws 都能看)。放"管理中心"下方。
  menus.push({
    path: '/monitoring',
    name: t('menu.monitoring'),
    icon: <DashboardOutlined />,
    children: [
      {
        path: '/monitoring/fsx',
        name: t('menu.fsxPerformance'),
        icon: <HddOutlined />,
      },
      {
        path: '/monitoring/kueue',
        name: t('menu.queue'),
        icon: <UnorderedListOutlined />,
      },
    ],
  });

  // 产品文档已移到顶栏右上角链接 (新窗口打开), 不再放左侧菜单。
  // 临时隐藏未开放功能菜单入口 (config/features.ts); 顶层过滤即可, 这三项都非嵌套子菜单。
  return menus.filter((m) => !isHiddenFeaturePath(m.path));
};

/** Derive a healthy/warn/danger status pip from a workspace's GPU quota usage. */
const wsStatusClass = (used: number, quota: number): string => {
  const ratio = quota === 0 ? 0 : used / quota;
  if (ratio >= 0.85) return 'ws-status-dot ws-status-dot--danger';
  if (ratio >= 0.6) return 'ws-status-dot ws-status-dot--warn';
  return 'ws-status-dot ws-status-dot--ok';
};

interface WorkspaceGpuSnapshot {
  used: number;
  quota: number;
}

export default function MainLayout() {
  const { t } = useTranslation('layout');
  const navigate = useNavigate();
  const location = useLocation();
  const params = useParams();
  const wsId = useActiveWorkspaceId();
  const currentUser = useAppStore((s) => s.currentUser);
  const [apiTokenOpen, setApiTokenOpen] = useState(false);
  const themeMode = useAppStore((s) => s.themeMode);
  const setCurrentWorkspaceId = useAppStore((s) => s.setCurrentWorkspaceId);

  // Real-data workspace list + per-ws GPU snapshot for the header selector pip.
  // Fetch is fire-and-forget: failures collapse to the mock behavior (all-ok)
  // rather than blocking the layout.
  const [realWorkspaces, setRealWorkspaces] = useState<Workspace[]>([]);
  const [gpuMap, setGpuMap] = useState<Record<string, WorkspaceGpuSnapshot>>({});
  // 当前用户是否为「当前 ws」的管理员 (role==admin)。用于「任务总览」菜单显隐。
  // 平台超管单独由 isAdmin 判断, 不依赖这个。
  const [isCurrentWsAdmin, setIsCurrentWsAdmin] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const ws = await listWorkspaces();
        if (cancelled) return;
        setRealWorkspaces(ws);
        const entries = await Promise.all(
          ws.map(async (w): Promise<[string, WorkspaceGpuSnapshot]> => {
            const [qRes, uRes] = await Promise.allSettled([
              getWorkspaceQuota(w.id),
              getWorkspaceQuotaUsage(w.id),
            ]);
            const quota =
              qRes.status === 'fulfilled'
                ? aggregateQuota(qRes.value.resources).totalAccelerators
                : 0;
            const used =
              uRes.status === 'fulfilled' ? uRes.value.totals.accelerators : 0;
            return [w.id, { used, quota }];
          }),
        );
        if (!cancelled) setGpuMap(Object.fromEntries(entries));
      } catch {
        // swallow — header selector falls back to an empty list.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // URL 里带了 :wsId 时,自动同步到 store,侧栏菜单/切换器跟上当前上下文
  // 避免 store 里残留旧 ws-001 导致菜单链接 404
  useEffect(() => {
    if (params.wsId && params.wsId !== wsId) {
      setCurrentWorkspaceId(params.wsId);
    }
  }, [params.wsId, wsId, setCurrentWorkspaceId]);

  const isAdmin = currentUser?.is_admin === true;

  // 选定 ws 后拉成员列表, 判断当前用户在该 ws 是否为 admin (任务总览菜单显隐用)。
  // 平台超管无需判断 (isAdmin 直通); 非超管才查 membership。
  useEffect(() => {
    if (isAdmin) {
      setIsCurrentWsAdmin(false); // 超管走 isAdmin 分支, 此值无意义
      return;
    }
    if (!wsId) {
      setIsCurrentWsAdmin(false);
      return;
    }
    let cancelled = false;
    const myId = currentUser?.id;
    (async () => {
      try {
        const members = await listMembers(wsId);
        if (cancelled) return;
        const me = members.find((m) => m.user_id === myId);
        setIsCurrentWsAdmin(me?.role === 'admin');
      } catch {
        if (!cancelled) setIsCurrentWsAdmin(false); // 拉不到 → 保守隐藏
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [wsId, isAdmin, currentUser?.id]);

  // ws 管理员 / 平台超管 共用的"管理类"可见性闸: 任务总览 + 资源模版 都用它。
  // (资源模版是 workspace 级, ws 管理员即可维护; 后端写闸 is_ws_admin 同口径。)
  const canManage = isAdmin || isCurrentWsAdmin;

  // 在 /docs 路径下时, 左侧菜单只渲文档树 (新窗口打开的"产品文档"独立浏览模式),
  // 文档间内部跳转保留, 工作空间/管理菜单收起避免干扰阅读。
  const inDocs = location.pathname.startsWith('/docs');
  const menuData = useMemo(
    () => (inDocs ? buildDocsMenu(t) : buildMenu(t, wsId, isAdmin, canManage)),
    [t, inDocs, wsId, isAdmin, canManage],
  );

  // 子菜单展开状态受控: 「管理中心 (/admin)」永远在 openKeys 里 (点其他菜单
  // 不会让它收起, 切换工作空间也保持展开)。其它子菜单仍可手动开关 (透传给 onOpenChange)。
  // ProLayout 内部默认会按当前 path 重算 openKeys, 这里覆盖它。
  const [extraOpenKeys, setExtraOpenKeys] = useState<string[]>([]);
  // 侧栏折叠状态受控。
  const [collapsed, setCollapsed] = useState(false);
  // 子菜单是否强制收起 (独立于 collapsed): 折叠前先收子菜单, 等收起动画跑完再折侧栏,
  // 否则子菜单收起 + 侧栏折叠同帧发生, 视觉上子项"最后才被收进去"卡顿。
  const [submenuClosed, setSubmenuClosed] = useState(false);
  const openKeys = useMemo(
    () =>
      submenuClosed || collapsed
        ? []
        : inDocs
          ? extraOpenKeys
          : Array.from(new Set(['/admin', ...extraOpenKeys])),
    [submenuClosed, collapsed, inDocs, extraOpenKeys],
  );

  // 折叠: 先收子菜单 (submenuClosed=true) → 等子菜单收起动画 (~200ms) → 再折侧栏。
  // 展开: 立即展开侧栏, 再放开子菜单。
  const handleCollapse = (next: boolean) => {
    if (next) {
      setSubmenuClosed(true);
      window.setTimeout(() => setCollapsed(true), 200);
    } else {
      setCollapsed(false);
      setSubmenuClosed(false);
    }
  };

  const handleWorkspaceChange = (nextId: string) => {
    setCurrentWorkspaceId(nextId);
    // If we're inside a workspace route, jump to the same sub-route under the new ws.
    const match = location.pathname.match(/^\/workspaces\/[^/]+(\/.*)?$/);
    const suffix = match?.[1] ?? '';
    navigate(`/workspaces/${nextId}${suffix}`);
  };

  /** Workspace options rendered with a colored status pip (real data). */
  const workspaceOptions = useMemo(
    () =>
      realWorkspaces.map((w) => {
        const snap = gpuMap[w.id] ?? { used: 0, quota: 0 };
        return {
          value: w.id,
          label: (
            <span>
              <span className={wsStatusClass(snap.used, snap.quota)} />
              {w.display_name}
            </span>
          ),
        };
      }),
    [realWorkspaces, gpuMap],
  );

  return (
    <ProLayout
      title="HyperPod Platform"
      logo={false}
      layout="mix"
      fixSiderbar
      fixedHeader
      navTheme={themeMode === 'dark' ? 'realDark' : 'light'}
      collapsed={collapsed}
      onCollapse={handleCollapse}
      // 内容区上限 1280px (13" MacBook 逻辑分辨率) 并居中: 宽屏不拉伸、窄屏自适应收缩。
      // 用 maxWidth 而非固定 width — 否则窗口/缩放窄于 1280 时 marginInline:auto 会算出
      // 负 margin 把内容拉到固定侧栏底下 (内容压住左侧菜单)。
      contentStyle={{ maxWidth: 1280, marginInline: 'auto' }}
      location={{ pathname: location.pathname }}
      menuDataRender={() => menuData}
      // 受控子菜单展开: openKeys 强行包含 /admin (管理中心永远展开),
      // 用户手动开/关其它子菜单 → onOpenChange 同步到 extraOpenKeys。
      // openKeys 必须给内层 antd Menu (menuProps), ProLayout 自己的 menu 配置不认 openKeys。
      menuProps={{
        openKeys,
        onOpenChange: (keys: string[]) => setExtraOpenKeys(keys),
      }}
      menuItemRender={(item, dom) => {
        // disabled (未选工作空间) 的项: 不可点, 包 Tooltip 提示; 不包 Link 避免跳转。
        if (item.disabled) {
          return (
            <Tooltip title={t('header.selectWorkspaceFirst')} placement="right">
              <span>{dom}</span>
            </Tooltip>
          );
        }
        return item.path ? <Link to={item.path}>{dom}</Link> : dom;
      }}
      headerTitleRender={(_logo, title) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, height: '100%' }}>
          <img
            src="/logo.svg"
            alt="logo"
            style={{ height: 28, width: 28, display: 'block', flexShrink: 0 }}
          />
          <span style={{ fontWeight: 600, letterSpacing: 0.2, lineHeight: 1 }}>{title}</span>
        </div>
      )}
      // 左 (工作空间选择器) + 右 (API Token / 用户) 都放进 headerContentRender 自渲染,
      // 不用 actionsRender —— ProLayout 会给 actionsRender 每项套带 hover 灰背景的 wrapper,
      // 那个盒子撑满 header 盖住底部分割线; 自渲染则完全由我们控制, 无多余盒子。
      headerContentRender={() => (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            width: '100%',
            paddingLeft: 16,
          }}
        >
          {/* 左: 当前工作空间选择器 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span
              style={{
                fontSize: 12,
                color: 'rgba(0,0,0,0.45)',
                letterSpacing: 0.3,
                whiteSpace: 'nowrap',
              }}
            >
              {t('header.currentWorkspace')}
            </span>
            <Select
              value={wsId}
              style={{ width: 240 }}
              onChange={handleWorkspaceChange}
              options={workspaceOptions}
              optionLabelProp="label"
              placeholder={t('header.selectWorkspace')}
            />
          </div>

          {/* 中间弹性留白, 把右侧内容推到最右 */}
          <div style={{ flex: 1 }} />

          {/* 右: 产品文档 + API Token + 用户 + 角色 — 字号统一 13px, 垂直居中对齐 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 13 }}>
            {/* 语言切换 (中文 / English) */}
            <LanguageSwitcher />
            {/* 产品文档: 新窗口打开 /docs, 文档站独立浏览模式 (左侧菜单只显文档树) */}
            <a
              href="/docs/overview"
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                fontSize: 13,
                color: 'inherit',
                whiteSpace: 'nowrap',
              }}
            >
              <BookOutlined style={{ color: 'rgba(0,0,0,0.45)' }} />
              {t('header.docs')}
            </a>
            {/* 故障诊断手册: 新窗口打开 GPU 节点故障排查 Runbook, 与产品文档并列的独立入口 */}
            <a
              href="/docs/gpu-fault-runbook"
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                fontSize: 13,
                color: 'inherit',
                whiteSpace: 'nowrap',
              }}
            >
              <MedicineBoxOutlined style={{ color: 'rgba(0,0,0,0.45)' }} />
              {t('header.runbook')}
            </a>
            {/* API Docs: 新窗口打开 Scalar API Reference (/api/scalar), 消费后端 /api/openapi.json */}
            <a
              href="/api/scalar"
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                fontSize: 13,
                color: 'inherit',
                whiteSpace: 'nowrap',
              }}
            >
              <ApiOutlined style={{ color: 'rgba(0,0,0,0.45)' }} />
              {t('header.apiReference')}
            </a>
            {/* 图标贴近文字: 不用 Button 的 icon 槽 (默认间距大), 改放进内容里自控 gap */}
            <span
              onClick={() => setApiTokenOpen(true)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                fontSize: 13,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              <KeyOutlined style={{ color: 'rgba(0,0,0,0.45)' }} />
              API Token
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <Avatar
                size={24}
                icon={<UserOutlined />}
                style={{ backgroundColor: '#e6f4ff', color: '#1677ff' }}
              />
              <span style={{ fontWeight: 500, fontSize: 13, whiteSpace: 'nowrap' }}>
                {currentUser?.display_name ?? '...'}
              </span>
              {/* 角色标签: 优先显平台超管, 其次当前 ws 管理员; 普通成员不显避免噪音 */}
              {(isAdmin || isCurrentWsAdmin) && (
                <Tag
                  color="blue"
                  style={{ marginInlineEnd: 0, fontWeight: 'normal', fontSize: 13 }}
                >
                  {isAdmin ? t('header.platformAdmin') : t('header.workspaceAdmin')}
                </Tag>
              )}
            </span>
          </div>
        </div>
      )}
    >
      <Outlet />
      <ApiTokenModal open={apiTokenOpen} onClose={() => setApiTokenOpen(false)} />
    </ProLayout>
  );
}
