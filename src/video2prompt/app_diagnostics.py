"""应用诊断信息。"""

from __future__ import annotations

from pathlib import Path


def build_diagnostics_report(
    *,
    app_version: str,
    port: int,
    config_path: Path,
    cache_db_path: Path,
    log_path: Path,
    last_error_message: str,
) -> str:
    return "\n".join(
        [
            f"app_version: {app_version}",
            f"port: {port}",
            f"config_path: {config_path}",
            f"cache_db_path: {cache_db_path}",
            f"log_path: {log_path}",
            f"last_error: {last_error_message}",
        ]
    )
