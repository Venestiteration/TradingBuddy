#!/usr/bin/env bash
# 启动 AI 投研助手 MVP（本机单进程 FastAPI）
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
  for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
        PYTHON_BIN="$candidate"
        break
      fi
    fi
  done
fi
if [ -z "$PYTHON_BIN" ]; then
  echo "需要 Python 3.10+，请安装后重试。" >&2
  exit 1
fi

if [ ! -d .venv ]; then
  echo "==> 创建虚拟环境（使用 $PYTHON_BIN）"
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if ! python -c "import fastapi, uvicorn, akshare, openai" >/dev/null 2>&1; then
  echo "==> 安装依赖"
  python -m pip install --upgrade pip >/dev/null
  python -m pip install -r requirements.txt
fi

if [ ! -f .env ]; then
  echo "==> 生成 .env（请编辑填写 OPENAI_API_KEY 与 OPENAI_MODEL）"
  cp .env.example .env
fi

echo "==> 启动服务：http://127.0.0.1:${APP_PORT:-8000}"
exec python -m uvicorn app.main:app --host "${APP_HOST:-127.0.0.1}" --port "${APP_PORT:-8000}"
