"""Douyin 解析客户端。"""

from __future__ import annotations

from typing import Any

import httpx

from .errors import ParserError, ParserRetryableError
from .models import ParseResult


class ParserClient:
    """解析服务客户端。"""

    RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 30,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    async def parse_video(self, url: str) -> ParseResult:
        close_client = False
        client = self._http_client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout_seconds)
            close_client = True

        try:
            endpoint = f"{self.base_url}/api/hybrid/video_data"
            resp = await client.get(endpoint, params={"url": url})
            if resp.status_code in self.RETRYABLE_STATUS:
                raise ParserRetryableError(f"解析服务状态码 {resp.status_code}: {resp.text[:300]}")
            if resp.status_code >= 400:
                raise ParserError(f"解析服务状态码 {resp.status_code}: {resp.text[:300]}")

            payload = resp.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                raise ParserRetryableError("解析结果为空或格式错误")

            video_data = data.get("video")
            if not isinstance(video_data, dict):
                raise ParserRetryableError("解析结果缺少 video 字段")

            video_url = self.select_video_url(video_data)
            aweme_id = str(data.get("aweme_id") or data.get("aweme_detail", {}).get("aweme_id") or "").strip()
            if not aweme_id:
                # aweme_id 缺失不阻塞流程，但尽量保持可追踪
                aweme_id = "unknown"

            return ParseResult(aweme_id=aweme_id, video_url=video_url, raw_data=data)
        except httpx.TimeoutException as exc:
            raise ParserRetryableError(f"解析请求超时: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ParserRetryableError(f"解析请求异常: {exc}") from exc
        except ValueError as exc:
            raise ParserRetryableError(f"解析 JSON 失败: {exc}") from exc
        finally:
            if close_client:
                await client.aclose()

    def select_video_url(self, video_data: dict[str, Any]) -> str:
        bit_rate_list = video_data.get("bit_rate")
        candidates: list[tuple[int, str]] = []

        if isinstance(bit_rate_list, list):
            for item in bit_rate_list:
                if not isinstance(item, dict):
                    continue
                is_h265 = int(item.get("is_h265", 0))
                if is_h265 != 0:
                    continue

                play_addr = item.get("play_addr") if isinstance(item.get("play_addr"), dict) else {}
                height = item.get("height", play_addr.get("height", 0))
                try:
                    height_int = int(height)
                except (TypeError, ValueError):
                    height_int = 0
                if height_int > 1080 and height_int != 0:
                    continue

                url_list = play_addr.get("url_list") if isinstance(play_addr.get("url_list"), list) else []
                if not url_list:
                    continue
                try:
                    bitrate = int(item.get("bit_rate", 0))
                except (TypeError, ValueError):
                    bitrate = 0
                candidates.append((bitrate, str(url_list[0])))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

        fallback_h264 = self._pick_url(video_data.get("play_addr_h264"))
        if fallback_h264:
            return fallback_h264

        fallback_play = self._pick_url(video_data.get("play_addr"))
        if fallback_play:
            return fallback_play

        raise ParserRetryableError("无法从解析结果中提取可用视频直链")

    @staticmethod
    def _pick_url(node: Any) -> str | None:
        if not isinstance(node, dict):
            return None
        url_list = node.get("url_list")
        if isinstance(url_list, list) and url_list:
            return str(url_list[0])
        return None

    async def health_check(self) -> tuple[bool, str]:
        """检查解析服务可达性。"""

        close_client = False
        client = self._http_client
        if client is None:
            client = httpx.AsyncClient(timeout=min(self.timeout_seconds, 5))
            close_client = True
        try:
            # 尝试访问 docs 或根路径，避免调用真实解析。
            for endpoint in ("/docs", "/"):
                try:
                    resp = await client.get(f"{self.base_url}{endpoint}")
                    if resp.status_code < 500:
                        return True, f"解析服务可用（{resp.status_code}）"
                except Exception:
                    continue
            return False, "解析服务不可达，请先启动 Douyin_TikTok_Download_API"
        finally:
            if close_client:
                await client.aclose()
