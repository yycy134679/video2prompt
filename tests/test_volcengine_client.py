from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from video2prompt.errors import GeminiRetryableError
from video2prompt.volcengine_client import VolcengineClient


def test_volcengine_build_request_body_contains_video_and_text() -> None:
    client = VolcengineClient(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        endpoint_id="ep-test",
        target_model="seed-2.0-lite",
        api_key="x",
    )
    body = client.build_request_body(
        video_uri="https://example.com/video.mp4",
        user_prompt="请总结视频",
        fps=1.2,
    )

    assert body["model"] == "ep-test"
    content = body["messages"][0]["content"]
    assert content[0]["type"] == "video_url"
    assert content[0]["video_url"]["url"] == "https://example.com/video.mp4"
    assert content[0]["video_url"]["fps"] == 1.2
    assert content[1]["type"] == "text"
    assert content[1]["text"] == "请总结视频"
    assert body["thinking"]["type"] == "enabled"
    assert body["reasoning_effort"] == "medium"


def test_volcengine_build_request_body_disabled_thinking_skip_reasoning_effort() -> None:
    client = VolcengineClient(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        endpoint_id="ep-test",
        target_model="seed-2.0-lite",
        api_key="x",
        thinking_type="disabled",
        reasoning_effort="high",
    )
    body = client.build_request_body(
        video_uri="https://example.com/video.mp4",
        user_prompt="请总结视频",
        fps=1.0,
    )
    assert body["thinking"]["type"] == "disabled"
    assert "reasoning_effort" not in body


def test_volcengine_interpret_video_success() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization", "")
        captured["path"] = request.url.path
        captured["payload"] = request.content.decode("utf-8")
        return httpx.Response(
            status_code=200,
            headers={"x-request-id": "req-chat-1"},
            json={
                "choices": [{"message": {"content": "视频解读结果"}}],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 22,
                    "reasoning_tokens": 3,
                    "cached_tokens": 1,
                },
            },
        )

    async def _run() -> tuple[str, float]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(timeout=30, transport=transport) as http_client:
            client = VolcengineClient(
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                endpoint_id="ep-test",
                target_model="seed-2.0-lite",
                api_key="volc_key",
                http_client=http_client,
            )
            return await client.interpret_video(
                video_uri="https://example.com/video.mp4",
                user_prompt="请总结视频",
                fps=2.0,
            )

    text, fps_used = asyncio.run(_run())
    payload = json.loads(captured["payload"])
    assert captured["auth"] == "Bearer volc_key"
    assert captured["path"] == "/api/v3/chat/completions"
    assert payload["model"] == "ep-test"
    assert payload["messages"][0]["content"][0]["video_url"]["url"] == "https://example.com/video.mp4"
    assert text == "视频解读结果"
    assert fps_used == 2.0


def test_volcengine_interpret_video_success_with_observation() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            headers={"x-request-id": "req-chat-2"},
            json={
                "choices": [{"message": {"content": "视频解读结果"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            },
        )

    async def _run() -> dict[str, int | str]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(timeout=30, transport=transport) as http_client:
            client = VolcengineClient(
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                endpoint_id="ep-test",
                target_model="seed-2.0-lite",
                api_key="volc_key",
                http_client=http_client,
            )
            await client.interpret_video(
                video_uri="https://example.com/video.mp4",
                user_prompt="请总结视频",
                fps=2.0,
            )
            return client.consume_last_observation()

    observation = asyncio.run(_run())
    assert observation["prompt_tokens"] == 1
    assert observation["completion_tokens"] == 2
    assert observation["request_id"] == "req-chat-2"


def test_volcengine_429_is_retryable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=429,
            json={
                "error": {
                    "code": "RequestBurstTooFast",
                    "message": "burst too fast",
                    "request_id": "req-burst-1",
                }
            },
        )

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(timeout=30, transport=transport) as http_client:
            client = VolcengineClient(
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                endpoint_id="ep-test",
                target_model="seed-2.0-lite",
                api_key="volc_key",
                http_client=http_client,
            )
            await client.interpret_video(
                video_uri="https://example.com/video.mp4",
                user_prompt="请总结视频",
                fps=2.0,
            )

    with pytest.raises(GeminiRetryableError) as exc_info:
        asyncio.run(_run())
    assert "RequestBurstTooFast" in str(exc_info.value)
    assert "req-burst-1" in str(exc_info.value)
