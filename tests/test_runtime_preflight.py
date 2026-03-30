from __future__ import annotations

from pathlib import Path

import pytest

from video2prompt.runtime_preflight import run_runtime_preflight


def test_run_runtime_preflight_flags_unwritable_cache_dir(tmp_path: Path) -> None:
    cache_parent = tmp_path / "cache-parent"
    cache_parent.write_text("block", encoding="utf-8")
    ffprobe_path = tmp_path / "ffprobe"
    ffprobe_path.write_text("binary", encoding="utf-8")

    issues = run_runtime_preflight(
        cache_db_path=cache_parent / "cache.db",
        exports_dir=tmp_path / "exports",
        ffprobe_path=ffprobe_path,
        has_api_key=True,
    )

    assert [issue.code for issue in issues] == ["cache_path_unwritable"]
    assert issues[0].blocking is True


def test_run_runtime_preflight_creates_missing_exports_dir_when_writable(
    tmp_path: Path,
) -> None:
    ffprobe_path = tmp_path / "ffprobe"
    ffprobe_path.write_text("binary", encoding="utf-8")

    issues = run_runtime_preflight(
        cache_db_path=tmp_path / "data" / "cache.db",
        exports_dir=tmp_path / "exports",
        ffprobe_path=ffprobe_path,
        has_api_key=True,
    )

    assert issues == []
    assert (tmp_path / "exports").is_dir()


def test_run_runtime_preflight_flags_unwritable_exports_dir(tmp_path: Path) -> None:
    exports_dir = tmp_path / "exports"
    exports_dir.write_text("block", encoding="utf-8")
    ffprobe_path = tmp_path / "ffprobe"
    ffprobe_path.write_text("binary", encoding="utf-8")

    issues = run_runtime_preflight(
        cache_db_path=tmp_path / "data" / "cache.db",
        exports_dir=exports_dir,
        ffprobe_path=ffprobe_path,
        has_api_key=True,
    )

    assert [issue.code for issue in issues] == ["exports_dir_unwritable"]
    assert issues[0].blocking is True


def test_run_runtime_preflight_flags_missing_ffprobe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)

    issues = run_runtime_preflight(
        cache_db_path=tmp_path / "data" / "cache.db",
        exports_dir=tmp_path / "exports",
        ffprobe_path=Path("ffprobe"),
        has_api_key=True,
    )

    assert any(issue.code == "ffprobe_missing" for issue in issues)


def test_run_runtime_preflight_flags_missing_api_key(tmp_path: Path) -> None:
    ffprobe_path = tmp_path / "ffprobe"
    ffprobe_path.write_text("binary", encoding="utf-8")

    issues = run_runtime_preflight(
        cache_db_path=tmp_path / "data" / "cache.db",
        exports_dir=tmp_path / "exports",
        ffprobe_path=ffprobe_path,
        has_api_key=False,
    )

    assert any(issue.code == "api_key_missing" and issue.blocking for issue in issues)
