"""ffprobe macOS bundling helpers."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


SYSTEM_LIBRARY_PREFIXES = (
    "/System/Library/",
    "/usr/lib/",
)
RUNTIME_RELATIVE_PREFIXES = (
    "@executable_path/",
    "@loader_path/",
    "@rpath/",
)


def parse_otool_libraries(output: str) -> list[str]:
    libraries: list[str] = []
    for line in output.splitlines()[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        libraries.append(stripped.split(" (", 1)[0])
    return libraries


def is_system_library(path: str) -> bool:
    return path.startswith(SYSTEM_LIBRARY_PREFIXES)


def is_runtime_relative_library(path: str) -> bool:
    return path.startswith(RUNTIME_RELATIVE_PREFIXES)


def dependency_install_name(path: Path) -> str:
    return f"@executable_path/lib/{path.name}"


def dylib_install_name(path: Path) -> str:
    return f"@loader_path/{path.name}"


def run_otool(path: Path) -> str:
    result = subprocess.run(
        ["otool", "-L", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def collect_non_system_dependencies(
    binary_path: Path,
    otool_runner=run_otool,
) -> list[Path]:
    pending = [binary_path]
    seen: set[Path] = set()
    collected: set[Path] = set()

    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        for library in parse_otool_libraries(otool_runner(current)):
            if is_system_library(library) or is_runtime_relative_library(library):
                continue
            library_path = Path(library)
            if library_path not in collected:
                collected.add(library_path)
                pending.append(library_path)

    return sorted(collected)


def run_install_name_tool(*args: str) -> None:
    subprocess.run(["install_name_tool", *args], check=True)


def codesign_binary(path: Path) -> None:
    subprocess.run(["codesign", "--force", "--sign", "-", str(path)], check=True)


def assert_no_external_non_system_dependencies(
    binary_path: Path,
    otool_runner=run_otool,
) -> None:
    external = [
        library
        for library in parse_otool_libraries(otool_runner(binary_path))
        if not is_system_library(library) and not is_runtime_relative_library(library)
    ]
    if external:
        raise RuntimeError(
            "仍存在外部非系统依赖: " + ", ".join(sorted(external))
        )


def prepare_ffprobe_bundle(
    ffprobe_path: Path,
    lib_dir: Path,
    otool_runner=run_otool,
) -> list[Path]:
    lib_dir.mkdir(parents=True, exist_ok=True)
    bundled = []
    dependencies = collect_non_system_dependencies(ffprobe_path, otool_runner=otool_runner)

    for dependency in dependencies:
        target = lib_dir / dependency.name
        shutil.copy2(dependency, target)
        target.chmod(0o755)
        bundled.append(target)

    for dependency in dependencies:
        run_install_name_tool(
            "-change",
            str(dependency),
            dependency_install_name(dependency),
            str(ffprobe_path),
        )

    for bundled_path in bundled:
        original_dependency = next(item for item in dependencies if item.name == bundled_path.name)
        run_install_name_tool("-id", dylib_install_name(original_dependency), str(bundled_path))
        for nested in parse_otool_libraries(otool_runner(original_dependency)):
            if is_system_library(nested):
                continue
            nested_path = Path(nested)
            run_install_name_tool(
                "-change",
                str(nested_path),
                dylib_install_name(nested_path),
                str(bundled_path),
            )
        codesign_binary(bundled_path)

    codesign_binary(ffprobe_path)
    assert_no_external_non_system_dependencies(ffprobe_path, otool_runner=otool_runner)
    return bundled


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a distributable ffprobe bundle")
    parser.add_argument("ffprobe_path", type=Path)
    parser.add_argument("lib_dir", type=Path)
    args = parser.parse_args()
    prepare_ffprobe_bundle(args.ffprobe_path, args.lib_dir)


if __name__ == "__main__":
    main()
