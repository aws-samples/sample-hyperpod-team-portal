/**
 * Public surface of the devinstance feature.
 *
 * Other code (router, Workspace Dashboard quick actions, etc.) should
 * import exclusively from `@/features/devinstance`; internals are free
 * to reshuffle without breaking external callers.
 */

// Route-level pages
export { default as DevList } from './pages/List';
export { default as DevDetail } from './pages/Detail';
export { default as DevInstanceCreate } from './pages/Create';

// API surface (functions + types) — other features (e.g. Workspace
// Dashboard) already consume a handful of these for quick-action cards.
export * from './api/client';
