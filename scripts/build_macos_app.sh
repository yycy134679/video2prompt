#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build"
SPEC_FILE="$ROOT_DIR/packaging/video2prompt-macos.spec"
FFPROBE_BIN="$ROOT_DIR/packaging/bin/ffprobe"
FFPROBE_LIB_DIR="$ROOT_DIR/packaging/bin/lib"
APP_BUNDLE_NAME="视频分析.app"
ZIP_NAME="视频分析-macos.zip"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
fi

cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR/src:${PYTHONPATH:-}"

for path in app.py config.yaml .env.example docs/product_prompt_template.xlsx docs/视频复刻提示词.md docs/视频脚本拆解分析.md docs/视频内容审查.md; do
  if [ ! -f "$path" ]; then
    echo "缺少构建资源: $path" >&2
    exit 1
  fi
done

if [ ! -f "$FFPROBE_BIN" ]; then
  echo "缺少 ffprobe 二进制: $FFPROBE_BIN" >&2
  echo "请先准备可分发的 macOS ffprobe 到 packaging/bin/ffprobe" >&2
  exit 1
fi

if [ ! -x "$FFPROBE_BIN" ]; then
  chmod +x "$FFPROBE_BIN"
fi

mkdir -p "$FFPROBE_LIB_DIR"
"$PYTHON_BIN" -m video2prompt.ffprobe_bundle "$FFPROBE_BIN" "$FFPROBE_LIB_DIR"

file "$FFPROBE_BIN"
otool -L "$FFPROBE_BIN"
"$FFPROBE_BIN" -version >/dev/null

if ! "$PYTHON_BIN" -m PyInstaller --version >/dev/null 2>&1; then
  echo "未安装 PyInstaller，请先执行: $PYTHON_BIN -m pip install pyinstaller" >&2
  exit 1
fi

rm -rf "$BUILD_DIR" "$DIST_DIR"
"$PYTHON_BIN" -m PyInstaller "$SPEC_FILE" --noconfirm
PYTHONPATH=src "$PYTHON_BIN" scripts/check_packaged_modules.py \
  "build/video2prompt-macos/PYZ-00.toc" \
  "build/video2prompt-macos/xref-video2prompt-macos.html" \
  "build/video2prompt-macos/warn-video2prompt-macos.txt"

if [ ! -d "$DIST_DIR/$APP_BUNDLE_NAME" ]; then
  echo "构建失败，未生成 $DIST_DIR/$APP_BUNDLE_NAME" >&2
  exit 1
fi

ditto -c -k --sequesterRsrc --keepParent "$DIST_DIR/$APP_BUNDLE_NAME" "$DIST_DIR/$ZIP_NAME"
PYTHONPATH=src "$PYTHON_BIN" scripts/check_packaged_modules.py \
  "build/video2prompt-macos/PYZ-00.toc" \
  "build/video2prompt-macos/xref-video2prompt-macos.html"

if [ "${VIDEO2PROMPT_RUN_SMOKE_TEST:-0}" = "1" ]; then
  PYTHONPATH=src "$PYTHON_BIN" scripts/smoke_test_macos_app.py "dist/视频分析.app"
fi

echo "构建完成: $DIST_DIR/$APP_BUNDLE_NAME"
echo "分发包: $DIST_DIR/$ZIP_NAME"
