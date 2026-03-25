from __future__ import annotations

from pathlib import Path

from video2prompt.ffprobe_bundle import (
    assert_no_external_non_system_dependencies,
    collect_non_system_dependencies,
    dependency_install_name,
    dylib_install_name,
    is_system_library,
    is_runtime_relative_library,
    parse_otool_libraries,
)


def test_parse_otool_libraries_extracts_dependency_paths() -> None:
    output = """packaging/bin/ffprobe:
\t/opt/homebrew/Cellar/ffmpeg/8.0.1_2/lib/libavdevice.62.dylib (compatibility version 62.0.0, current version 62.1.100)
\t/System/Library/Frameworks/Foundation.framework/Versions/C/Foundation (compatibility version 300.0.0, current version 3423.0.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1351.0.0)
"""

    assert parse_otool_libraries(output) == [
        "/opt/homebrew/Cellar/ffmpeg/8.0.1_2/lib/libavdevice.62.dylib",
        "/System/Library/Frameworks/Foundation.framework/Versions/C/Foundation",
        "/usr/lib/libSystem.B.dylib",
    ]


def test_is_system_library_recognizes_macos_system_paths() -> None:
    assert is_system_library("/System/Library/Frameworks/Foundation.framework/Versions/C/Foundation") is True
    assert is_system_library("/usr/lib/libSystem.B.dylib") is True
    assert is_system_library("/opt/homebrew/opt/x264/lib/libx264.165.dylib") is False


def test_is_runtime_relative_library_recognizes_bundled_paths() -> None:
    assert is_runtime_relative_library("@executable_path/lib/libavformat.62.dylib") is True
    assert is_runtime_relative_library("@loader_path/libavutil.60.dylib") is True
    assert is_runtime_relative_library("/opt/homebrew/lib/libavutil.60.dylib") is False


def test_collect_non_system_dependencies_walks_dependency_graph() -> None:
    outputs = {
        "/tmp/ffprobe": """/tmp/ffprobe:
\t/opt/homebrew/lib/libavformat.62.dylib (compatibility version 62.0.0, current version 62.3.100)
\t/System/Library/Frameworks/Foundation.framework/Versions/C/Foundation (compatibility version 300.0.0, current version 3423.0.0)
""",
        "/opt/homebrew/lib/libavformat.62.dylib": """/opt/homebrew/lib/libavformat.62.dylib:
\t/opt/homebrew/lib/libavcodec.62.dylib (compatibility version 62.0.0, current version 62.11.100)
\t/usr/lib/libz.1.dylib (compatibility version 1.0.0, current version 1.2.12)
""",
        "/opt/homebrew/lib/libavcodec.62.dylib": """/opt/homebrew/lib/libavcodec.62.dylib:
\t/opt/homebrew/lib/libavutil.60.dylib (compatibility version 60.0.0, current version 60.8.100)
""",
        "/opt/homebrew/lib/libavutil.60.dylib": "/opt/homebrew/lib/libavutil.60.dylib:\n",
    }

    dependencies = collect_non_system_dependencies(
        Path("/tmp/ffprobe"),
        otool_runner=lambda path: outputs[str(path)],
    )

    assert dependencies == [
        Path("/opt/homebrew/lib/libavcodec.62.dylib"),
        Path("/opt/homebrew/lib/libavformat.62.dylib"),
        Path("/opt/homebrew/lib/libavutil.60.dylib"),
    ]


def test_dependency_install_name_points_ffprobe_to_bundled_lib() -> None:
    assert (
        dependency_install_name(Path("/opt/homebrew/lib/libavformat.62.dylib"))
        == "@executable_path/lib/libavformat.62.dylib"
    )


def test_dylib_install_name_uses_loader_relative_path() -> None:
    assert (
        dylib_install_name(Path("/opt/homebrew/lib/libavformat.62.dylib"))
        == "@loader_path/libavformat.62.dylib"
    )


def test_assert_no_external_non_system_dependencies_rejects_homebrew_paths() -> None:
    try:
        assert_no_external_non_system_dependencies(
            Path("/tmp/ffprobe"),
            otool_runner=lambda path: """/tmp/ffprobe:
\t@executable_path/lib/libavformat.62.dylib (compatibility version 62.0.0, current version 62.3.100)
\t/opt/homebrew/lib/libavcodec.62.dylib (compatibility version 62.0.0, current version 62.11.100)
""",
        )
    except RuntimeError as exc:
        assert "/opt/homebrew/lib/libavcodec.62.dylib" in str(exc)
    else:
        raise AssertionError("预期应拒绝外部 Homebrew 依赖")
