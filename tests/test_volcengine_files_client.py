from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from video2prompt.errors import ModelError
from video2prompt.volcengine_files_client import VolcengineFilesClient


def test_download_video_to_temp_over_limit(tmp_path: Path) -> None:
    data = b"x" * (2 * 1024 * 1024)  # 2 MiB

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, content=data)

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = VolcengineFilesClient(
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                api_key="k",
                http_client=http_client,
            )
            await client.download_video_to_temp("https://example.com/video.mp4", max_mb=1)

    with pytest.raises(ModelError):
        asyncio.run(_run())


def test_upload_file_success(tmp_path: Path) -> None:
    sample = tmp_path / "sample.mp4"
    sample.write_bytes(b"fake-mp4")
    captured: dict[str, str | bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["method"] = request.method
        captured["body"] = request.content
        return httpx.Response(status_code=200, json={"id": "file-123"})

    async def _run() -> str:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = VolcengineFilesClient(
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                api_key="k",
                http_client=http_client,
            )
            return await client.upload_file(str(sample), fps=1.0, expire_days=7)

    file_id = asyncio.run(_run())
    assert file_id == "file-123"
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v3/files"
    body = captured["body"]
    assert isinstance(body, bytes)
    assert b'name="purpose"' in body
    assert b"user_data" in body


def test_poll_file_ready_timeout() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json={"id": "file-123", "status": "processing"})

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = VolcengineFilesClient(
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                api_key="k",
                http_client=http_client,
            )
            await client.poll_file_ready("file-123", timeout_seconds=1)

    with pytest.raises(ModelError):
        asyncio.run(_run())


def test_delete_file_best_effort() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=500, text="server error")

    async def _run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = VolcengineFilesClient(
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                api_key="k",
                http_client=http_client,
            )
            await client.delete_file("file-123")

    asyncio.run(_run())
