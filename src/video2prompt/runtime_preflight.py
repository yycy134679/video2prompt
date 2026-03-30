"""开始执行前的运行时自检。"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PreflightIssue:
    code: str
    message: str
    blocking: bool


def _ensure_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        return False
    return path.is_dir()


def _ffprobe_available(ffprobe_path: Path) -> bool:
    if ffprobe_path.exists():
        return True
    if len(ffprobe_path.parts) == 1:
        return shutil.which(ffprobe_path.name) is not None
    return False


def run_runtime_preflight(
    *,
    cache_db_path: Path,
    exports_dir: Path,
    ffprobe_path: Path,
    has_api_key: bool,
) -> list[PreflightIssue]:
    issues: list[PreflightIssue] = []
    if not _ensure_writable_dir(cache_db_path.parent):
        issues.append(PreflightIssue("cache_path_unwritable", "缓存目录不可写", True))
    if not _ensure_writable_dir(exports_dir):
        issues.append(PreflightIssue("exports_dir_unwritable", "导出目录不可写", True))
    if not _ffprobe_available(ffprobe_path):
        issues.append(PreflightIssue("ffprobe_missing", "未找到 ffprobe", False))
    if not has_api_key:
        issues.append(PreflightIssue("api_key_missing", "缺少 API Key", True))
    return issues
