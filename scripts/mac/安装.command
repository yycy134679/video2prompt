#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=./common.sh
source "$SCRIPT_DIR/common.sh"

echo "开始安装 video2prompt（mac 版本地交付）..."
ensure_runtime_dirs
require_python311
check_network "https://www.python.org/"
check_network "https://pypi.org/"
check_network "https://github.com/"

echo "创建应用虚拟环境..."
python3 -m venv "$APP_VENV"
"$APP_PYTHON" -m pip install --upgrade pip setuptools wheel

echo "安装应用依赖..."
"$APP_PYTHON" -m pip install -e "$ROOT_DIR"

PARSER_TAG="$("$APP_PYTHON" - <<'PY'
from video2prompt.managed_parser_service import PARSER_RELEASE_TAG
print(PARSER_RELEASE_TAG)
PY
)"
ZIP_URL="https://github.com/Evil0ctal/Douyin_TikTok_Download_API/archive/refs/tags/${PARSER_TAG}.zip"
ZIP_FILE="$MANAGED_ROOT/downloads/douyin_tiktok_download_api-${PARSER_TAG}.zip"
TMP_DIR="$MANAGED_ROOT/downloads/tmp_extract_${PARSER_TAG}"

mkdir -p "$MANAGED_ROOT/downloads"

if [[ ! -f "$PARSER_SOURCE/app/main.py" ]]; then
  echo "下载受管解析服务 ${PARSER_TAG}..."
  curl --location --fail --retry 3 "$ZIP_URL" -o "$ZIP_FILE"

  echo "解压受管解析服务..."
  rm -rf "$TMP_DIR"
  mkdir -p "$TMP_DIR"
  ditto -x -k "$ZIP_FILE" "$TMP_DIR"

  EXTRACTED_DIR="$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  if [[ -z "$EXTRACTED_DIR" ]]; then
    echo "解析服务解压失败，未找到源码目录。"
    exit 1
  fi

  mkdir -p "$PARSER_SOURCE"
  ditto "$EXTRACTED_DIR" "$PARSER_SOURCE"
  rm -rf "$TMP_DIR"
else
  echo "检测到已存在的受管解析服务源码，跳过下载。"
fi

echo "创建解析服务虚拟环境..."
python3 -m venv "$PARSER_VENV"
"$PARSER_PYTHON" -m pip install --upgrade pip setuptools wheel

echo "安装解析服务依赖..."
"$PARSER_PYTHON" -m pip install -r "$PARSER_SOURCE/requirements.txt"

echo "写入受管解析服务默认配置..."
"$APP_PYTHON" -m video2prompt.local_service_cli parser prepare --clear-cookies

echo
echo "安装完成。"
echo "下一步：请双击 scripts/mac/启动.command 启动服务。"
echo "首次进入页面后，请先到“首次设置 / 环境检查”填写火山方舟配置和抖音 Cookie。"
