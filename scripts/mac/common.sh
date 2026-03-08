#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_VENV="$ROOT_DIR/.venv"
APP_PYTHON="$APP_VENV/bin/python"
MANAGED_ROOT="$ROOT_DIR/.managed/douyin_tiktok_download_api"
PARSER_SOURCE="$MANAGED_ROOT/source"
PARSER_VENV="$MANAGED_ROOT/venv"
PARSER_PYTHON="$PARSER_VENV/bin/python"
RUNTIME_DIR="$ROOT_DIR/.runtime"
STREAMLIT_PID_FILE="$RUNTIME_DIR/streamlit.pid"
STREAMLIT_LOG_FILE="$RUNTIME_DIR/streamlit.log"
STREAMLIT_URL="http://127.0.0.1:8501"

export PYTHONPATH="$ROOT_DIR/src:${PYTHONPATH:-}"

ensure_runtime_dirs() {
  mkdir -p "$RUNTIME_DIR" "$ROOT_DIR/logs" "$ROOT_DIR/data" "$ROOT_DIR/exports" "$MANAGED_ROOT"
}

is_pid_running() {
  local pid="$1"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  kill -0 "$pid" >/dev/null 2>&1
}

open_python_download_page() {
  open "https://www.python.org/downloads/macos/" >/dev/null 2>&1 || true
}

require_python311() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "未检测到 python3，请先安装 Python 3.11 或更高版本。"
    open_python_download_page
    exit 1
  fi

  if ! python3 - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
  then
    echo "检测到的 Python 版本过低，请安装 Python 3.11 或更高版本。"
    python3 --version || true
    open_python_download_page
    exit 1
  fi
}

check_network() {
  local url="$1"
  if ! curl --head --silent --location --fail "$url" >/dev/null 2>&1; then
    echo "网络检查失败：无法访问 $url"
    exit 1
  fi
}

require_app_installation() {
  if [[ ! -x "$APP_PYTHON" ]]; then
    echo "未检测到应用虚拟环境，请先运行 scripts/mac/安装.command"
    exit 1
  fi
}

require_parser_installation() {
  if [[ ! -x "$PARSER_PYTHON" ]] || [[ ! -f "$PARSER_SOURCE/app/main.py" ]]; then
    echo "未检测到受管解析服务，请先运行 scripts/mac/安装.command"
    exit 1
  fi
}

read_streamlit_pid() {
  if [[ -f "$STREAMLIT_PID_FILE" ]]; then
    tr -d '[:space:]' <"$STREAMLIT_PID_FILE"
  fi
}

wait_for_streamlit() {
  local deadline=$((SECONDS + 25))
  while [[ $SECONDS -lt $deadline ]]; do
    if curl --silent --fail "$STREAMLIT_URL/_stcore/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}
