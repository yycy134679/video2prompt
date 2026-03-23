"""运行时路径解析。"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    resource_root: Path
    app_support_dir: Path
    docs_dir: Path
    data_dir: Path
    logs_dir: Path
    exports_dir: Path
    binaries_dir: Path

    @classmethod
    def for_dev(cls, repo_root: Path) -> "RuntimePaths":
        app_support_dir = repo_root / ".runtime" / "video2prompt"
        return cls(
            resource_root=repo_root,
            app_support_dir=app_support_dir,
            docs_dir=repo_root / "docs",
            data_dir=app_support_dir / "data",
            logs_dir=app_support_dir / "logs",
            exports_dir=app_support_dir / "exports",
            binaries_dir=repo_root / "bin",
        )

    @classmethod
    def for_bundle(cls, bundle_root: Path, home_dir: Path) -> "RuntimePaths":
        app_support_dir = home_dir / "Library" / "Application Support" / "video2prompt"
        return cls(
            resource_root=bundle_root,
            app_support_dir=app_support_dir,
            docs_dir=bundle_root / "docs",
            data_dir=app_support_dir / "data",
            logs_dir=app_support_dir / "logs",
            exports_dir=app_support_dir / "exports",
            binaries_dir=bundle_root / "bin",
        )


def build_runtime_paths(
    repo_root: Path | None = None,
    home_dir: Path | None = None,
) -> RuntimePaths:
    resolved_home_dir = home_dir or Path.home()
    if getattr(sys, "frozen", False):
        return RuntimePaths.for_bundle(
            bundle_root=Path(getattr(sys, "_MEIPASS")),
            home_dir=resolved_home_dir,
        )
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]
    return RuntimePaths.for_dev(repo_root=repo_root)
