/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// 静态文档 (Runbook 等) 用 `?raw` 整篇导入 markdown 原文, 交给 react-markdown 渲染。
declare module '*.md?raw' {
  const content: string;
  export default content;
}
