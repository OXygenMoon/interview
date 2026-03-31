# 多阶段构建：第一阶段 - 构建前端
FROM node:16-alpine as frontend-builder

WORKDIR /app/frontend

# 复制前端package文件
COPY frontend/package*.json ./

# 安装前端依赖
RUN npm install --production

# 复制前端源代码
COPY frontend/. .

# 构建前端
RUN npm run build

# 第二阶段 - 构建后端
FROM node:16-alpine as backend-builder

WORKDIR /app/backend

# 复制后端package文件
COPY backend/package*.json ./

# 安装后端依赖
RUN npm install --production

# 复制后端源代码
COPY backend/. .

# 第三阶段 - 最终镜像
FROM node:16-alpine

WORKDIR /app

# 复制后端依赖和源代码
COPY --from=backend-builder /app/backend/package*.json ./
COPY --from=backend-builder /app/backend/node_modules ./node_modules
COPY --from=backend-builder /app/backend/server.js ./
COPY --from=backend-builder /app/backend/routes ./routes
COPY --from=backend-builder /app/backend/templates ./templates

# 复制前端构建文件
COPY --from=frontend-builder /app/frontend/dist ./public

# 创建必要目录
RUN mkdir -p data

# 设置环境变量
ENV NODE_ENV=production
ENV PORT=3001
ENV JWT_SECRET=resume-builder-secret-key-change-in-production

# 暴露端口
EXPOSE 3001

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3001/api/health || exit 1

# 启动命令
CMD ["node", "server.js"]