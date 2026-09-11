# MemWeave 前端多阶段构建（tasks.md 决策记录2：node:20 构建 → nginx:1.24 托管）
# nginx 配置由 docker-compose.yml 以 volume 挂载（deploy/nginx.conf），避免构建上下文越界
FROM node:20-alpine AS build-stage

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --registry=https://registry.npmmirror.com || npm install --registry=https://registry.npmmirror.com
COPY . .
RUN npm run build

FROM nginx:1.24-alpine

COPY --from=build-stage /app/dist /usr/share/nginx/html

EXPOSE 80
