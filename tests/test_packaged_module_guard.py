from __future__ import annotations

from pathlib import Path

import pytest

from video2prompt.packaged_module_guard import scan_text_for_forbidden_modules


def test_scan_text_for_forbidden_modules_flags_pytest() -> None:
    hits = scan_text_for_forbidden_modules(
        "hidden import 'pytest' loaded from xref",
        source=Path("build/video2prompt-macos/xref-video2prompt-macos.html"),
    )

    assert hits == [
        "build/video2prompt-macos/xref-video2prompt-macos.html: pytest"
    ]


def test_scan_text_for_forbidden_modules_flags_streamlit_and_pandas_testing() -> None:
    text = "\n".join(
        [
            "module streamlit.testing.v1.app_test",
            "module pandas._testing",
        ]
    )

    hits = scan_text_for_forbidden_modules(
        text,
        source=Path("build/video2prompt-macos/PYZ-00.toc"),
    )

    assert hits == [
        "build/video2prompt-macos/PYZ-00.toc: streamlit.testing",
        "build/video2prompt-macos/PYZ-00.toc: pandas._testing",
    ]


def test_scan_text_for_forbidden_modules_ignores_clean_runtime_modules() -> None:
    hits = scan_text_for_forbidden_modules(
        "video2prompt.task_scheduler\nvideo2prompt.cache_store",
        source=Path("build/video2prompt-macos/xref-video2prompt-macos.html"),
    )

    assert hits == []


def test_scan_artifact_paths_raises_when_forbidden_module_found(tmp_path: Path) -> None:
    from video2prompt.packaged_module_guard import scan_artifact_paths

    target = tmp_path / "xref-video2prompt-macos.html"
    target.write_text("hidden import 'streamlit.testing'", encoding="utf-8")

    with pytest.raises(RuntimeError, match="streamlit.testing"):
        scan_artifact_paths([target])


def test_scan_text_for_forbidden_modules_ignores_numpy_pytesttester() -> None:
    hits = scan_text_for_forbidden_modules(
        "module numpy._pytesttester",
        source=Path("build/video2prompt-macos/PYZ-00.toc"),
    )

    assert hits == []


def test_scan_artifact_paths_ignores_excluded_module_in_xref(tmp_path: Path) -> None:
    from video2prompt.packaged_module_guard import scan_artifact_paths

    target = tmp_path / "xref-video2prompt-macos.html"
    target.write_text(
        "\n".join(
            [
                '<a name="pandas.testing"></a>',
                '<a target="code" href="" type="text/plain"><tt>pandas.testing</tt></a>',
                '<span class="moduletype">ExcludedModule</span>',
            ]
        ),
        encoding="utf-8",
    )

    scan_artifact_paths([target])


def test_scan_artifact_paths_ignores_missing_module_in_xref(tmp_path: Path) -> None:
    from video2prompt.packaged_module_guard import scan_artifact_paths

    target = tmp_path / "xref-video2prompt-macos.html"
    target.write_text(
        "\n".join(
            [
                '<a name="\'_pytest.outcomes\'"></a>',
                '<a target="code" href="" type="text/plain"><tt>\'_pytest.outcomes\'</tt></a>',
                '<span class="moduletype">MissingModule</span>',
            ]
        ),
        encoding="utf-8",
    )

    scan_artifact_paths([target])


def test_scan_artifact_paths_ignores_warn_file_missing_module_entries(tmp_path: Path) -> None:
    from video2prompt.packaged_module_guard import scan_artifact_paths

    target = tmp_path / "warn-video2prompt-macos.txt"
    target.write_text("missing module named pytest", encoding="utf-8")

    scan_artifact_paths([target])
