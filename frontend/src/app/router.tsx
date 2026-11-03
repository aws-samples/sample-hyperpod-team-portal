/**
 * App-level router scaffold.
 *
 * Wave 1 skeleton: this file is intentionally a placeholder. The real
 * route table still lives in `src/router.tsx` and is consumed by `App.tsx`.
 *
 * TODO(Wave 3): aggregate feature route lists here. Each feature should
 * export a `routes` array from `src/features/<feature>/index.ts`, e.g.:
 *
 *   // features/devinstance/index.ts
 *   export const devInstanceRoutes: RouteObject[] = [
 *     { path: 'workspaces/:wsId/dev', element: <DevList /> },
 *     { path: 'workspaces/:wsId/dev/:id', element: <DevDetail /> },
 *   ];
 *
 * Then this file composes them:
 *
 *   const element = useRoutes([
 *     { path: '/', element: <DefaultRedirect /> },
 *     { path: '/login', element: <Login /> },
 *     {
 *       path: '/',
 *       element: <MainLayout />,
 *       children: [
 *         ...workspaceRoutes,
 *         ...devInstanceRoutes,
 *         ...trainingRoutes,
 *         ...inferenceRoutes,
 *         ...adminRoutes,
 *         ...assetRoutes,
 *       ],
 *     },
 *     { path: '*', element: <DefaultRedirect /> },
 *   ]);
 *
 * Until then, importing this module is a no-op.
 */

// Intentionally empty. See header comment.
export {};
