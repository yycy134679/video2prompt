from __future__ import annotations

from pathlib import Path

from video2prompt.packaged_smoke import smoke_test_app


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
