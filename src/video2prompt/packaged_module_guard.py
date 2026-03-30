"""打包产物中的禁用模块扫描。"""

from __future__ import annotations

import re
from pathlib import Path


FORBIDDEN_MODULE_PREFIXES = (
    "pytest",
    "_pytest",
    "streamlit.testing",
    "pandas.testing",
    "pandas._testing",
)
MODULE_TOKEN_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
)
XREF_NODE_PATTERN = re.compile(
    r"<a target=\"code\" href=\"[^\"]*\" type=\"text/plain\"><tt>(?P<module>[^<]+)</tt></a>\s*<span class=\"moduletype\">(?P<moduletype>[^<]+)</span>",
    re.DOTALL,
)


def _matches_forbidden_prefix(module_name: str) -> list[str]:
    hits: list[str] = []
    for prefix in FORBIDDEN_MODULE_PREFIXES:
        if module_name == prefix or module_name.startswith(f"{prefix}."):
            hits.append(prefix)
    return hits


def scan_text_for_forbidden_modules(text: str, source: Path) -> list[str]:
    hits: list[str] = []
    seen: set[str] = set()
    for token in MODULE_TOKEN_PATTERN.findall(text):
        for prefix in _matches_forbidden_prefix(token):
            hit = f"{source.as_posix()}: {prefix}"
            if hit in seen:
                continue
            seen.add(hit)
            hits.append(hit)
    return hits


def scan_xref_for_forbidden_modules(text: str, source: Path) -> list[str]:
    hits: list[str] = []
    seen: set[str] = set()
    matched_node = False
    for match in XREF_NODE_PATTERN.finditer(text):
        matched_node = True
        if match.group("moduletype") in {"ExcludedModule", "MissingModule"}:
            continue
        module_name = match.group("module").strip("'\"")
        for prefix in _matches_forbidden_prefix(module_name):
            hit = f"{source.as_posix()}: {prefix}"
            if hit in seen:
                continue
            seen.add(hit)
            hits.append(hit)
    if not matched_node:
        return scan_text_for_forbidden_modules(text, source=source)
    return hits


def scan_artifact_paths(paths: list[Path]) -> None:
    hits: list[str] = []
    for path in paths:
        if not path.exists() or path.is_dir():
            continue
        if path.name.startswith("warn-"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if path.name.startswith("xref-") and path.suffix == ".html":
            hits.extend(scan_xref_for_forbidden_modules(text, source=path))
            continue
        hits.extend(scan_text_for_forbidden_modules(text, source=path))
    if hits:
        raise RuntimeError("\n".join(hits))
