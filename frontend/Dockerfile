# 前端镜像: 多阶段 — vite build 出静态产物, nginx 托管.
# API 走相对路径 /api/v1 (同域), 由 ALB Ingress 路由到后端, nginx 不代理 API.

# ---- build 阶段 ----
FROM public.ecr.aws/docker/library/node:20-slim AS build
WORKDIR /app
RUN npm install -g pnpm
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build          # 产物在 dist/ (vite 默认)

# ---- serve 阶段 ----
FROM public.ecr.aws/nginx/nginx:stable
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
