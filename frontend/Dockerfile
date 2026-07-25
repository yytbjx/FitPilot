# FitPilot 前端镜像：Vite 构建产物 + nginx 静态托管 / 反向代理

# ---------- 构建阶段 ----------
FROM node:20-alpine AS builder

# pnpm 由 corepack 提供（packageManager 未声明时固定一个主版本）
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate

WORKDIR /build

# 生产 API 基址：走 nginx 反代（可在 build 时 --build-arg 覆盖）
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=${VITE_API_BASE}

# 仅拷贝锁文件，先装依赖（利用缓存）
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# 拷贝源码并构建（.dockerignore 排除 node_modules / dist / .env）
COPY . .
RUN pnpm build

# ---------- 运行阶段 ----------
FROM nginx:alpine

# SPA + /api 反代配置（含 SSE 支持）
COPY nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1/"]

CMD ["nginx", "-g", "daemon off;"]
