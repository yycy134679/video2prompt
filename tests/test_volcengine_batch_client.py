from __future__ import annotations

import asyncio
import json

import httpx

from video2prompt.volcengine_batch_client import VolcengineBatchClient


def test_batch_chat_contains_reasoning_effort() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/batch/chat/completions"
        payload = json.loads(request.content.decode("utf-8"))
        req = payload["requests"][0]
        assert req["thinking"]["type"] == "enabled"
        assert req["reasoning_effort"] == "low"
        return httpx.Response(
            status_code=200,
            json={
                "results": [
                    {
                        "custom_id": "1",
                        "response": {
                            "choices": [{"message": {"content": "批量结果"}}],
                            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
                            "request_id": "req-batch-1",
                        },
                    }
                ]
            },
        )

    async def _run() -> list[dict[str, object]]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = VolcengineBatchClient(
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                endpoint_id="ep-test",
                api_key="k",
                reasoning_effort="low",
                http_client=http_client,
            )
            return await client.batch_chat(
                [
                    {
                        "custom_id": "1",
                        "video_url": "https://example.com/video.mp4",
                        "fps": 1.0,
                        "prompt": "请分析",
                    }
                ]
            )

    results = asyncio.run(_run())
    assert len(results) == 1
    assert results[0]["custom_id"] == "1"
    assert results[0]["text"] == "批量结果"
