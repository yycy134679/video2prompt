from __future__ import annotations

from pathlib import Path

import pytest

from video2prompt.user_state_store import UserStateStore


def test_user_state_store_creates_default_file_when_missing(tmp_path: Path) -> None:
    path = tmp_path / "user_state.yaml"
    store = UserStateStore(path)

    state = store.load()

    assert path.exists()
    assert not state.has_cookie
    assert state.douyin_cookie == ""
    assert state.updated_at == ""
    assert state.volcengine_api_key == ""
    assert state.volcengine_model == ""
    assert state.ai_settings_updated_at == ""


def test_user_state_store_save_and_clear_cookie(tmp_path: Path) -> None:
    path = tmp_path / "user_state.yaml"
    store = UserStateStore(path)

    saved = store.save_cookie("foo=bar; baz=qux")
    cleared = store.clear_cookie()

    assert saved.has_cookie
    assert saved.updated_at
    assert store.load().douyin_cookie == ""
    assert not cleared.has_cookie


def test_user_state_store_save_and_clear_ai_settings(tmp_path: Path) -> None:
    path = tmp_path / "user_state.yaml"
    store = UserStateStore(path)

    saved = store.save_ai_settings("api-key", "doubao-test-model")
    cleared = store.clear_ai_settings()

    assert saved.volcengine_api_key == "api-key"
    assert saved.volcengine_model == "doubao-test-model"
    assert saved.ai_settings_updated_at
    assert store.load().volcengine_api_key == ""
    assert store.load().volcengine_model == ""
    assert cleared.ai_settings_updated_at == ""


def test_user_state_store_preserves_ai_settings_when_saving_cookie(tmp_path: Path) -> None:
    path = tmp_path / "user_state.yaml"
    store = UserStateStore(path)
    store.save_ai_settings("api-key", "doubao-test-model")

    state = store.save_cookie("foo=bar")

    assert state.douyin_cookie == "foo=bar"
    loaded = store.load()
    assert loaded.volcengine_api_key == "api-key"
    assert loaded.volcengine_model == "doubao-test-model"


def test_user_state_store_preserves_cookie_when_saving_ai_settings(tmp_path: Path) -> None:
    path = tmp_path / "user_state.yaml"
    store = UserStateStore(path)
    store.save_cookie("foo=bar")

    state = store.save_ai_settings("api-key", "doubao-test-model")

    assert state.volcengine_api_key == "api-key"
    loaded = store.load()
    assert loaded.douyin_cookie == "foo=bar"


def test_user_state_store_recovers_from_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "user_state.yaml"
    path.write_text("[]", encoding="utf-8")
    store = UserStateStore(path)

    state = store.load()

    assert state.douyin_cookie == ""
    assert state.updated_at == ""
    assert state.volcengine_api_key == ""
    assert state.volcengine_model == ""
    assert state.ai_settings_updated_at == ""
    assert "douyin_cookie" in path.read_text(encoding="utf-8")


def test_user_state_store_default_path_uses_runtime_app_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIDEO2PROMPT_APP_SUPPORT_DIR", str(tmp_path / "support"))

    store = UserStateStore()

    assert store.path == tmp_path / "support" / "user_state.yaml"
