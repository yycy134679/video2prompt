from __future__ import annotations

from pathlib import Path


SPEC_PATH = Path("packaging/video2prompt-macos.spec")


def test_spec_collects_streamlit_metadata() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    assert 'copy_metadata("streamlit")' in text


def test_spec_uses_onedir_collect_layout() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    assert "COLLECT(" in text
    assert "BUNDLE(" in text


def test_spec_collects_app_module_dependencies() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    assert 'collect_submodules("video2prompt")' in text
    assert '"app"' in text


def test_spec_marks_bundle_as_agent_app() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    assert "info_plist={" in text
    assert '"LSUIElement": True' in text


def test_spec_uses_project_icon_for_bundle() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    assert 'icon=os.path.join(ROOT_DIR, "icon.icns")' in text


def test_spec_sets_bundle_display_name_to_video_analysis() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    assert '"CFBundleDisplayName": "视频分析"' in text
    assert '"CFBundleName": "视频分析"' in text


def test_spec_sets_bundle_file_name_to_video_analysis() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    assert 'name="视频分析.app"' in text


def test_spec_collects_bundled_ffprobe_libraries() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    assert 'glob.glob(os.path.join(ROOT_DIR, "packaging", "bin", "lib", "*.dylib"))' in text
    assert '(library_path, "bin/lib")' in text
