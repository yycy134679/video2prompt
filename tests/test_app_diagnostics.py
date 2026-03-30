from __future__ import annotations

from pathlib import Path

from video2prompt.app_diagnostics import build_diagnostics_report


def test_build_diagnostics_report_contains_runtime_paths() -> None:
    report = build_diagnostics_report(
        app_version="1.0.0",
        port=8512,
        config_path=Path("/tmp/config.yaml"),
        cache_db_path=Path("/tmp/cache.db"),
        log_path=Path("/tmp/app.log"),
        last_error_message="sqlite busy",
    )

    assert "1.0.0" in report
    assert "/tmp/config.yaml" in report
    assert "sqlite busy" in report
