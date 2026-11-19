#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-8090}"

echo "=== 1. 构建 EchoMind 前端界面 ==="
cd "$ROOT_DIR/web"
if [ ! -d "node_modules" ]; then
  npm install
fi
npm run build

echo "=== 2. 准备后端运行环境 ==="
cd "$ROOT_DIR/backend"
if [ ! -d ".venv" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 .venv || uv venv .venv
    uv pip install --python .venv/bin/python -e .
  else
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -e .
  fi
fi

echo "=== 3. 启动 EchoMind 服务 (http://0.0.0.0:${PORT}) ==="
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
