from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from video2prompt.errors import GeminiError, GeminiRetryableError
from video2prompt.volcengine_responses_client import VolcengineResponsesClient


def test_create_response_with_file_id_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/responses"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["reasoning_effort"] == "high"
        return httpx.Response(
            status_code=200,
            headers={"x-request-id": "req-resp-1"},
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "这是解析结果"},
                        ],
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 34},
            },
        )

    async def _run() -> dict[str, int | str]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = VolcengineResponsesClient(
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                endpoint_id="ep-test",
                api_key="k",
                reasoning_effort="high",
                http_client=http_client,
            )
            text = await client.create_response_with_file_id("file-123", "请分析视频")
            assert text == "这是解析结果"
            return client.consume_last_observation()

    observation = asyncio.run(_run())
    assert observation["prompt_tokens"] == 12
    assert observation["completion_tokens"] == 34
    assert observation["request_id"] == "req-resp-1"
    assert observation["api_mode"] == "responses"


def test_create_response_with_file_id_empty_output() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json={"output": []})

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = VolcengineResponsesClient(
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                endpoint_id="ep-test",
                api_key="k",
                http_client=http_client,
            )
            await client.create_response_with_file_id("file-123", "请分析视频")

    with pytest.raises(GeminiError):
        asyncio.run(_run())


def test_create_response_with_file_id_retryable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=500, text="server overloaded")

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = VolcengineResponsesClient(
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                endpoint_id="ep-test",
                api_key="k",
                http_client=http_client,
            )
            await client.create_response_with_file_id("file-123", "请分析视频")

    with pytest.raises(GeminiRetryableError):
        asyncio.run(_run())
