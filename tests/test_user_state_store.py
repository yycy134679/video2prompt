from __future__ import annotations

from pathlib import Path

from video2prompt.user_state_store import UserStateStore


def test_user_state_store_creates_default_file_when_missing(tmp_path: Path) -> None:
    path = tmp_path / "user_state.yaml"
    store = UserStateStore(path)

    state = store.load()

    assert path.exists()
    assert not state.has_cookie
    assert state.douyin_cookie == ""
    assert state.updated_at == ""


def test_user_state_store_save_and_clear_cookie(tmp_path: Path) -> None:
    path = tmp_path / "user_state.yaml"
    store = UserStateStore(path)

    saved = store.save_cookie("foo=bar; baz=qux")
    cleared = store.clear_cookie()

    assert saved.has_cookie
    assert saved.updated_at
    assert store.load().douyin_cookie == ""
    assert not cleared.has_cookie


def test_user_state_store_recovers_from_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "user_state.yaml"
    path.write_text("[]", encoding="utf-8")
    store = UserStateStore(path)

    state = store.load()

    assert state.douyin_cookie == ""
    assert state.updated_at == ""
    assert "douyin_cookie" in path.read_text(encoding="utf-8")
