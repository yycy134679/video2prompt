#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "未检测到 python3，请先安装 Python 3.11+"
  exit 1
fi

if ! python3 -c "import streamlit" >/dev/null 2>&1; then
  echo "依赖未安装，请先执行: pip install -e ."
  exit 1
fi

if [ ! -f ".env" ]; then
  echo "未找到 .env，请复制 .env.example 并填写 VOLCENGINE_API_KEY 或 ARK_API_KEY"
  exit 1
fi

export PYTHONPATH="$ROOT_DIR/src:${PYTHONPATH:-}"
python3 -m streamlit run app.py --server.headless=false
