from __future__ import annotations

import sys
from pathlib import Path

from video2prompt.runtime_paths import RuntimePaths, build_runtime_paths


def test_runtime_paths_in_dev_mode(tmp_path: Path) -> None:
    paths = RuntimePaths.for_dev(repo_root=tmp_path)

    assert paths.resource_root == tmp_path
    assert paths.docs_dir == tmp_path / "docs"
    assert paths.app_support_dir == tmp_path / ".runtime" / "video2prompt"


def test_runtime_paths_in_bundle_mode_uses_application_support(tmp_path: Path) -> None:
    paths = RuntimePaths.for_bundle(bundle_root=tmp_path / "bundle", home_dir=tmp_path / "home")

    assert paths.resource_root == tmp_path / "bundle"
    assert paths.app_support_dir == (
        tmp_path / "home" / "Library" / "Application Support" / "video2prompt"
    )
    assert paths.data_dir == paths.app_support_dir / "data"
    assert paths.logs_dir == paths.app_support_dir / "logs"
    assert paths.exports_dir == paths.app_support_dir / "exports"


def test_build_runtime_paths_prefers_frozen_bundle(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)

    paths = build_runtime_paths(home_dir=tmp_path / "home")

    assert paths.resource_root == tmp_path / "bundle"
    assert paths.binaries_dir == tmp_path / "bundle" / "bin"
