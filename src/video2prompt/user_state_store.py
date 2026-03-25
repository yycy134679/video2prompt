"""用户本地状态存储。"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime
import os
from pathlib import Path

import yaml



def resolve_default_user_state_path() -> Path:
    app_support_dir = os.getenv("VIDEO2PROMPT_APP_SUPPORT_DIR", "").strip()
    if app_support_dir:
        return Path(app_support_dir) / "user_state.yaml"
    return Path.home() / "Library" / "Application Support" / "video2prompt" / "user_state.yaml"


@dataclass(frozen=True)
class UserState:
    douyin_cookie: str = ""
    updated_at: str = ""
    volcengine_api_key: str = ""
    volcengine_model: str = ""
    ai_settings_updated_at: str = ""

    @property
    def has_cookie(self) -> bool:
        return bool(self.douyin_cookie.strip())

    @property
    def has_ai_settings(self) -> bool:
        return bool(self.volcengine_api_key.strip() and self.volcengine_model.strip())


class UserStateStore:
    """持久化抖音 Cookie，不写入 config.yaml 或 SQLite。"""

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path) if path is not None else resolve_default_user_state_path()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> UserState:
        self._ensure_parent_dir()
        if not self._path.exists():
            state = UserState()
            self._write_state(state)
            return state

        try:
            parsed = yaml.safe_load(self._path.read_text(encoding="utf-8"))
            data = {} if parsed is None else parsed
            if not isinstance(data, dict):
                raise ValueError("user_state.yaml 顶层必须是对象")
        except (OSError, ValueError, yaml.YAMLError):
            state = UserState()
            self._write_state(state)
            return state

        self._ensure_permissions()
        return UserState(
            douyin_cookie=str(data.get("douyin_cookie") or ""),
            updated_at=str(data.get("updated_at") or ""),
            volcengine_api_key=str(data.get("volcengine_api_key") or ""),
            volcengine_model=str(data.get("volcengine_model") or ""),
            ai_settings_updated_at=str(data.get("ai_settings_updated_at") or ""),
        )

    def save_cookie(self, cookie: str) -> UserState:
        normalized = (cookie or "").strip()
        if not normalized:
            raise ValueError("Cookie 不能为空")
        existing = self.load()
        state = replace(
            existing,
            douyin_cookie=normalized,
            updated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        self._write_state(state)
        return state

    def clear_cookie(self) -> UserState:
        state = replace(self.load(), douyin_cookie="", updated_at="")
        self._write_state(state)
        return state

    def save_ai_settings(self, api_key: str, model: str) -> UserState:
        normalized_api_key = (api_key or "").strip()
        normalized_model = (model or "").strip()
        if not normalized_api_key:
            raise ValueError("API Key 不能为空")
        if not normalized_model:
            raise ValueError("模型 ID 不能为空")

        existing = self.load()
        state = replace(
            existing,
            volcengine_api_key=normalized_api_key,
            volcengine_model=normalized_model,
            ai_settings_updated_at=datetime.now()
            .astimezone()
            .isoformat(timespec="seconds"),
        )
        self._write_state(state)
        return state

    def clear_ai_settings(self) -> UserState:
        state = replace(
            self.load(),
            volcengine_api_key="",
            volcengine_model="",
            ai_settings_updated_at="",
        )
        self._write_state(state)
        return state

    def has_cookie(self) -> bool:
        return self.load().has_cookie

    def _write_state(self, state: UserState) -> None:
        self._ensure_parent_dir()
        payload = {
            "douyin_cookie": state.douyin_cookie,
            "updated_at": state.updated_at,
            "volcengine_api_key": state.volcengine_api_key,
            "volcengine_model": state.volcengine_model,
            "ai_settings_updated_at": state.ai_settings_updated_at,
        }
        self._path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        self._ensure_permissions()

    def _ensure_parent_dir(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with suppress(OSError, NotImplementedError):
            self._path.parent.chmod(0o700)

    def _ensure_permissions(self) -> None:
        with suppress(OSError, NotImplementedError):
            self._path.chmod(0o600)
