#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build"
SPEC_FILE="$ROOT_DIR/packaging/video2prompt-macos.spec"
FFPROBE_BIN="$ROOT_DIR/packaging/bin/ffprobe"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
fi

cd "$ROOT_DIR"

for path in app.py config.yaml .env.example docs/product_prompt_template.xlsx docs/视频复刻提示词.md docs/视频内容审查.md; do
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

file "$FFPROBE_BIN"
otool -L "$FFPROBE_BIN"
"$FFPROBE_BIN" -version >/dev/null

if ! "$PYTHON_BIN" -m PyInstaller --version >/dev/null 2>&1; then
  echo "未安装 PyInstaller，请先执行: $PYTHON_BIN -m pip install pyinstaller" >&2
  exit 1
fi

rm -rf "$BUILD_DIR" "$DIST_DIR"
"$PYTHON_BIN" -m PyInstaller "$SPEC_FILE" --noconfirm

if [ ! -d "$DIST_DIR/video2prompt.app" ]; then
  echo "构建失败，未生成 $DIST_DIR/video2prompt.app" >&2
  exit 1
fi

ditto -c -k --sequesterRsrc --keepParent "$DIST_DIR/video2prompt.app" "$DIST_DIR/video2prompt-macos.zip"

echo "构建完成: $DIST_DIR/video2prompt.app"
echo "分发包: $DIST_DIR/video2prompt-macos.zip"
