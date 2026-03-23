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
