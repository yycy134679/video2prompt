from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/build_macos_app.sh")


def test_build_script_checks_for_video_analysis_app() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'APP_BUNDLE_NAME="视频分析.app"' in text
    assert '"$DIST_DIR/$APP_BUNDLE_NAME"' in text


def test_build_script_packages_video_analysis_zip() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'ZIP_NAME="视频分析-macos.zip"' in text
    assert '"$DIST_DIR/$ZIP_NAME"' in text
