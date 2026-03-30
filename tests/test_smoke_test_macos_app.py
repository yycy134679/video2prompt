from __future__ import annotations

from pathlib import Path

from video2prompt.packaged_smoke import _homepage_ready, smoke_test_app


def test_smoke_test_app_returns_1_when_healthcheck_fails(
    monkeypatch,  # noqa: ANN001
    tmp_path: Path,
) -> None:
    app_path = tmp_path / "视频分析.app"
    executable_dir = app_path / "Contents" / "MacOS"
    executable_dir.mkdir(parents=True)
    (executable_dir / "video2prompt").write_text("binary", encoding="utf-8")
    monkeypatch.setattr(
        "video2prompt.packaged_smoke.wait_for_healthcheck",
        lambda *_args, **_kwargs: False,
    )

    assert smoke_test_app(app_path) == 1


def test_smoke_test_app_returns_0_when_healthcheck_succeeds(
    monkeypatch,  # noqa: ANN001
    tmp_path: Path,
) -> None:
    app_path = tmp_path / "视频分析.app"
    executable_dir = app_path / "Contents" / "MacOS"
    executable_dir.mkdir(parents=True)
    (executable_dir / "video2prompt").write_text("binary", encoding="utf-8")
    monkeypatch.setattr(
        "video2prompt.packaged_smoke.wait_for_healthcheck",
        lambda *_args, **_kwargs: True,
    )

    assert smoke_test_app(app_path) == 0


def test_homepage_ready_accepts_streamlit_shell() -> None:
    assert _homepage_ready("<html><title>video2prompt</title>streamlit</html>") is True


def test_homepage_ready_rejects_unrelated_response() -> None:
    assert _homepage_ready("internal server error") is False
