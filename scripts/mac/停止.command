#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=./common.sh
source "$SCRIPT_DIR/common.sh"
cd "$ROOT_DIR"

ensure_runtime_dirs

STREAMLIT_PID="$(read_streamlit_pid)"
if [[ -n "${STREAMLIT_PID:-}" ]] && is_pid_running "$STREAMLIT_PID"; then
  echo "停止 Streamlit（PID=$STREAMLIT_PID）..."
  kill "$STREAMLIT_PID" >/dev/null 2>&1 || true

  deadline=$((SECONDS + 5))
  while [[ $SECONDS -lt $deadline ]]; do
    if ! is_pid_running "$STREAMLIT_PID"; then
      break
    fi
    sleep 1
  done

  if is_pid_running "$STREAMLIT_PID"; then
    kill -9 "$STREAMLIT_PID" >/dev/null 2>&1 || true
  fi
else
  echo "未检测到运行中的 Streamlit。"
fi
rm -f "$STREAMLIT_PID_FILE"

if [[ -x "$APP_PYTHON" ]]; then
  echo "停止受管解析服务..."
  "$APP_PYTHON" -m video2prompt.local_service_cli parser stop || true
else
  echo "未检测到应用虚拟环境，跳过解析服务停止命令。"
fi

echo "停止完成。"
