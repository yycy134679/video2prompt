from __future__ import annotations

import asyncio

import httpx
import pytest

import app
from video2prompt.errors import ModelError
from video2prompt.volcengine_files_client import VolcengineFilesClient
from video2prompt.volcengine_responses_client import VolcengineResponsesClient


def test_resolve_runtime_api_key_returns_empty_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    assert app.resolve_runtime_api_key({}) == ""


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
                endpoint_id="ep-test",
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
