"""火山 Files API 客户端。"""

from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from .errors import GeminiError, GeminiRetryableError


class VolcengineFilesClient:
    """封装视频下载、上传、轮询与清理。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: int = 90,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    async def download_video_to_temp(self, url: str, max_mb: int) -> str:
        """流式下载视频到临时文件，超过阈值立即终止。"""
        close_client = False
        client = self._http_client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True)
            close_client = True

        max_bytes = max(1, int(max_mb)) * 1024 * 1024
        fd, temp_path = tempfile.mkstemp(prefix="volc_video_", suffix=".mp4")
        os.close(fd)
        current_bytes = 0

        try:
            async with client.stream("GET", url, follow_redirects=True) as resp:
                if resp.status_code in {429, 500, 502, 503, 504}:
                    raise GeminiRetryableError(f"下载视频失败，状态码 {resp.status_code}: {resp.text[:300]}")
                if resp.status_code >= 400:
                    raise GeminiError(f"下载视频失败，状态码 {resp.status_code}: {resp.text[:300]}")

                with Path(temp_path).open("wb") as f:
                    async for chunk in resp.aiter_bytes():
                        if not chunk:
                            continue
                        current_bytes += len(chunk)
                        if current_bytes > max_bytes:
                            raise GeminiError(
                                f"视频文件超过 Files 上限（>{max_mb} MiB），已中断下载"
                            )
                        f.write(chunk)
            return temp_path
        except Exception:
            Path(temp_path).unlink(missing_ok=True)
            raise
        finally:
            if close_client:
                await client.aclose()

    async def upload_file(self, path: str, fps: float, model: str, expire_days: int = 7) -> str:
        """上传视频文件并返回 file_id。"""
        del fps  # File ID 路径不使用 fps，保留签名便于调度层统一调用。
        del model

        close_client = False
        client = self._http_client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout_seconds)
            close_client = True

        expire_at = int((datetime.now(timezone.utc) + timedelta(days=expire_days)).timestamp())
        file_name = Path(path).name or "video.mp4"
        url = f"{self.base_url}/files"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            with Path(path).open("rb") as f:
                resp = await client.post(
                    url,
                    headers=headers,
                    # 火山 Files API 要求 purpose=user_data，否则会返回 InvalidParameter。
                    data={"expire_at": str(expire_at), "purpose": "user_data"},
                    files={"file": (file_name, f, "video/mp4")},
                )
            if resp.status_code in {429, 500, 502, 503, 504}:
                raise GeminiRetryableError(f"上传文件失败，状态码 {resp.status_code}: {resp.text[:500]}")
            if resp.status_code >= 400:
                raise GeminiError(f"上传文件失败，状态码 {resp.status_code}: {resp.text[:500]}")

            payload = resp.json()
            file_id = payload.get("id") if isinstance(payload, dict) else None
            if not isinstance(file_id, str) or not file_id.strip():
                raise GeminiError(f"上传成功但未返回有效 file_id: {payload}")
            return file_id
        except ValueError as exc:
            raise GeminiRetryableError(f"上传文件返回 JSON 解析失败: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise GeminiRetryableError(f"上传文件超时: {exc}") from exc
        except httpx.HTTPError as exc:
            raise GeminiRetryableError(f"上传文件请求异常: {exc}") from exc
        finally:
            if close_client:
                await client.aclose()

    async def poll_file_ready(self, file_id: str, timeout_seconds: int) -> None:
        """轮询文件状态直到 active。"""
        close_client = False
        client = self._http_client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout_seconds)
            close_client = True

        url = f"{self.base_url}/files/{file_id}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        deadline = time.monotonic() + max(1, int(timeout_seconds))

        try:
            while True:
                resp = await client.get(url, headers=headers)
                if resp.status_code in {429, 500, 502, 503, 504}:
                    raise GeminiRetryableError(f"查询文件状态失败，状态码 {resp.status_code}: {resp.text[:500]}")
                if resp.status_code >= 400:
                    raise GeminiError(f"查询文件状态失败，状态码 {resp.status_code}: {resp.text[:500]}")

                payload = resp.json()
                status = ""
                if isinstance(payload, dict):
                    status = str(payload.get("status", "")).strip().lower()

                if status == "active":
                    return
                if status == "failed":
                    raise GeminiError(f"文件处理失败 file_id={file_id}: {payload}")

                if time.monotonic() >= deadline:
                    raise GeminiError(f"文件激活超时 file_id={file_id} timeout={timeout_seconds}s")
                await asyncio_sleep(1.5)
        except ValueError as exc:
            raise GeminiRetryableError(f"查询文件状态 JSON 解析失败: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise GeminiRetryableError(f"查询文件状态超时: {exc}") from exc
        except httpx.HTTPError as exc:
            raise GeminiRetryableError(f"查询文件状态请求异常: {exc}") from exc
        finally:
            if close_client:
                await client.aclose()

    async def delete_file(self, file_id: str) -> None:
        """删除文件（best-effort）。"""
        close_client = False
        client = self._http_client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout_seconds)
            close_client = True

        url = f"{self.base_url}/files/{file_id}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            resp = await client.delete(url, headers=headers)
            if resp.status_code >= 400:
                # 删除失败不阻塞主流程
                return
        except Exception:
            return
        finally:
            if close_client:
                await client.aclose()


async def asyncio_sleep(seconds: float) -> None:
    """本地封装，便于单测打桩。"""
    import asyncio

    await asyncio.sleep(seconds)
