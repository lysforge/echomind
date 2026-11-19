# Stage 1: 构建 React + Tailwind 前端静态产物
FROM node:22-alpine AS frontend
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: 构建 Python + FFmpeg 后端运行时
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ECHOMIND_DATA_DIR=/app/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend /app/backend
COPY clients /app/clients
COPY --from=frontend /build/dist /app/web/dist

RUN pip install --no-cache-dir -e /app/backend \
    && mkdir -p /app/data

WORKDIR /app/backend
EXPOSE 8090
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
