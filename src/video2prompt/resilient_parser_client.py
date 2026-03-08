"""带 yt-dlp 兜底的解析客户端。"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import ConfigError, ParserError, ParserRetryableError
from .managed_parser_service import ManagedParserService
from .models import ParseResult
from .parser_client import ParserClient


class YtDlpParserClient:
    """使用 yt-dlp 直连网页解析视频信息。"""

    def __init__(
        self,
        repo_root: str | Path | None = None,
        parser_root: str | Path | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.service = ManagedParserService(repo_root=repo_root, parser_root=parser_root)
        self.logger = logger or logging.getLogger("video2prompt")

    async def parse_video(self, url: str) -> ParseResult:
        return await asyncio.to_thread(self._parse_video_sync, url)

    def supports(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host.endswith("douyin.com") or host.endswith("tiktok.com")

    def _parse_video_sync(self, url: str) -> ParseResult:
        try:
            from yt_dlp import YoutubeDL
        except ImportError as exc:  # pragma: no cover
            raise ConfigError("未安装 yt-dlp，无法启用兜底解析") from exc

        if not self.supports(url):
            raise ParserError("yt-dlp 兜底当前仅支持 Douyin/TikTok 链接")

        cookie_text = self.service.get_cookie_for_url(url)
        ydl_opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "extract_flat": False,
        }

        with tempfile.TemporaryDirectory(prefix="video2prompt-ytdlp-") as temp_dir:
            if cookie_text:
                cookie_path = Path(temp_dir) / "cookies.txt"
                cookie_path.write_text(self._build_cookie_file(url, cookie_text), encoding="utf-8")
                ydl_opts["cookiefile"] = str(cookie_path)

            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

        if isinstance(info, dict) and isinstance(info.get("entries"), list):
            info = next((item for item in info["entries"] if isinstance(item, dict)), info)
        if not isinstance(info, dict):
            raise ParserRetryableError("yt-dlp 返回结果为空或格式错误")

        video_url = self._select_video_url(info)
        aweme_id = str(info.get("id") or self._extract_aweme_id(url) or "").strip() or "unknown"
        return ParseResult(aweme_id=aweme_id, video_url=video_url, raw_data=info)

    @staticmethod
    def _extract_aweme_id(url: str) -> str:
        path = (urlparse(url).path or "").rstrip("/")
        tail = path.rsplit("/", 1)[-1]
        return tail if tail.isdigit() else ""

    @staticmethod
    def _build_cookie_file(url: str, cookie_text: str) -> str:
        host = (urlparse(url).hostname or "").lower()
        domain = ".tiktok.com" if host.endswith("tiktok.com") else ".douyin.com"
        jar = SimpleCookie()
        jar.load(cookie_text)
        lines = ["# Netscape HTTP Cookie File"]
        for morsel in jar.values():
            lines.append(
                "\t".join(
                    [
                        domain,
                        "TRUE",
                        "/",
                        "FALSE",
                        "0",
                        morsel.key,
                        morsel.value,
                    ]
                )
            )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _select_video_url(info: dict[str, Any]) -> str:
        formats = info.get("formats")
        candidates: list[tuple[int, int, int, str]] = []
        if isinstance(formats, list):
            for item in formats:
                if not isinstance(item, dict):
                    continue
                if str(item.get("vcodec") or "none") == "none":
                    continue
                url = str(item.get("url") or "").strip()
                if not url:
                    continue
                protocol = str(item.get("protocol") or "").lower().strip()
                ext = str(item.get("ext") or "").lower().strip()
                if protocol.startswith("m3u8"):
                    continue
                try:
                    height = int(item.get("height") or 0)
                except (TypeError, ValueError):
                    height = 0
                if height > 1080 and height != 0:
                    continue
                ext_score = 1 if ext == "mp4" else 0
                try:
                    tbr = int(float(item.get("tbr") or 0))
                except (TypeError, ValueError):
                    tbr = 0
                candidates.append((ext_score, height, tbr, url))

        if candidates:
            candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
            return candidates[0][3]

        direct_url = str(info.get("url") or "").strip()
        if direct_url:
            return direct_url

        raise ParserRetryableError("yt-dlp 未提取到可用视频直链")


class ResilientParserClient:
    """优先使用本地 parser，失败时回退到 yt-dlp。"""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 30,
        http_client=None,
        repo_root: str | Path | None = None,
        parser_root: str | Path | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.primary = ParserClient(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            http_client=http_client,
        )
        self.fallback = YtDlpParserClient(repo_root=repo_root, parser_root=parser_root, logger=logger)
        self.logger = logger or logging.getLogger("video2prompt")

    async def parse_video(self, url: str) -> ParseResult:
        primary_error: Exception | None = None
        try:
            return await self.primary.parse_video(url)
        except (ParserError, ParserRetryableError) as exc:
            primary_error = exc
            self.logger.warning("主解析失败，开始尝试 yt-dlp 兜底: %s", exc)

        if not self.fallback.supports(url):
            if primary_error is not None:
                raise primary_error
            raise ParserRetryableError("不支持的链接类型")

        try:
            result = await self.fallback.parse_video(url)
            self.logger.info("yt-dlp 兜底解析成功 aweme_id=%s", result.aweme_id)
            return result
        except Exception as fallback_error:
            if primary_error is None:
                raise fallback_error
            raise ParserRetryableError(
                f"主解析失败：{primary_error}；yt-dlp 兜底也失败：{fallback_error}"
            ) from fallback_error

    async def health_check(self) -> tuple[bool, str]:
        return await self.primary.health_check()
