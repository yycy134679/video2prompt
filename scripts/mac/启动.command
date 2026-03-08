#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=./common.sh
source "$SCRIPT_DIR/common.sh"
cd "$ROOT_DIR"

ensure_runtime_dirs
require_app_installation
require_parser_installation

echo "启动受管解析服务..."
"$APP_PYTHON" -m video2prompt.local_service_cli parser start --wait-timeout 20

STREAMLIT_PID="$(read_streamlit_pid)"
if [[ -n "${STREAMLIT_PID:-}" ]] && is_pid_running "$STREAMLIT_PID"; then
  echo "检测到 Streamlit 已在运行（PID=$STREAMLIT_PID）。"
else
  echo "启动 Streamlit..."
  nohup "$APP_PYTHON" -m streamlit run "$ROOT_DIR/app.py" --server.headless=true --browser.gatherUsageStats=false >"$STREAMLIT_LOG_FILE" 2>&1 &
  echo "$!" >"$STREAMLIT_PID_FILE"

  if ! wait_for_streamlit; then
    echo "Streamlit 启动超时，请检查日志：$STREAMLIT_LOG_FILE"
    exit 1
  fi
fi

echo "打开浏览器：$STREAMLIT_URL"
open "$STREAMLIT_URL"
echo "启动完成。关闭此终端窗口不会影响已启动的服务。"
