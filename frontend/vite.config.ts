import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      // 后端全部走 /api 前缀 (业务 API + OpenAPI/Swagger/ReDoc/Scalar 文档),
      // 一条规则全转发到后端; /docs/* 留给前端「产品文档」SPA, 不代理.
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8800',
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
