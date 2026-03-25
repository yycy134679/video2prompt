from __future__ import annotations

import asyncio

import httpx
import pytest

import app
from video2prompt.errors import ModelError
from video2prompt.models import AppMode
from video2prompt.user_state_store import UserStateStore
from video2prompt.volcengine_files_client import VolcengineFilesClient
from video2prompt.volcengine_responses_client import VolcengineResponsesClient


def test_resolve_runtime_api_key_returns_empty_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    assert app.resolve_runtime_api_key({}) == ""


def test_resolve_runtime_ai_settings_prefers_user_state(tmp_path) -> None:
    store = UserStateStore(tmp_path / "user_state.yaml")
    store.save_ai_settings("saved-key", "saved-model")

    resolved = app.resolve_runtime_ai_settings(
        store,
        default_model="default-model",
        environ={"VOLCENGINE_API_KEY": "env-key"},
    )

    assert resolved.api_key == "saved-key"
    assert resolved.model == "saved-model"


def test_resolve_runtime_ai_settings_falls_back_to_env_and_default_model(tmp_path) -> None:
    store = UserStateStore(tmp_path / "user_state.yaml")

    resolved = app.resolve_runtime_ai_settings(
        store,
        default_model="default-model",
        environ={"ARK_API_KEY": "env-key"},
    )

    assert resolved.api_key == "env-key"
    assert resolved.model == "default-model"


def test_validate_runtime_ai_settings_requires_api_key_for_ai_modes() -> None:
    message = app.validate_runtime_ai_settings(
        AppMode.VIDEO_PROMPT,
        api_key="",
        model="doubao-test-model",
    )

    assert "API Key" in message


def test_validate_runtime_ai_settings_requires_model_for_ai_modes() -> None:
    message = app.validate_runtime_ai_settings(
        AppMode.CATEGORY_ANALYSIS,
        api_key="api-key",
        model="",
    )

    assert "模型 ID" in message


def test_validate_runtime_ai_settings_skips_duration_mode() -> None:
    message = app.validate_runtime_ai_settings(
        AppMode.DURATION_CHECK,
        api_key="",
        model="",
    )

    assert message == ""


def test_responses_client_raises_before_request_when_api_key_missing() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(status_code=200, json={})

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = VolcengineResponsesClient(
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                model="doubao-test-model",
                api_key="",
                http_client=http_client,
            )
            await client.create_response_with_file_id("file-123", "请分析视频")

    with pytest.raises(ModelError, match="API Key"):
        asyncio.run(_run())
    assert called is False


def test_files_client_raises_before_request_when_api_key_missing(tmp_path) -> None:
    called = False
    sample = tmp_path / "sample.mp4"
    sample.write_bytes(b"fake")

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(status_code=200, json={})

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = VolcengineFilesClient(
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                api_key="",
                http_client=http_client,
            )
            await client.upload_file(str(sample), fps=1.0, expire_days=7)

    with pytest.raises(ModelError, match="API Key"):
        asyncio.run(_run())
    assert called is False
