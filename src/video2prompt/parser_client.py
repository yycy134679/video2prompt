"""本地抖音解析客户端。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

import httpx

from .douyin_xbogus import XBogus
from .errors import (
    ParserClientSideError,
    ParserCookieRequiredError,
    ParserCookieRetryableError,
    ParserError,
    ParserRetryableError,
    ParserUnsupportedContentError,
)
from .models import ParseResult
from .user_state_store import UserStateStore

COOKIE_RETRY_HINT = "Cookie 可能失效或需要过验证码，请重新复制浏览器 Cookie"
COOKIE_REQUIRED_MESSAGE = "未配置抖音 Cookie，请先在页面中粘贴并保存"
UNSUPPORTED_IMAGE_MESSAGE = "当前仅支持抖音视频，不支持图集"
DEFAULT_DOUYIN_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


class ParserClient:
    """本地抖音解析客户端，兼容旧的 ParserClient 调用方式。"""

    RETRYABLE_STATUS = {401, 403, 412, 429, 500, 502, 503, 504}
    DIRECT_LINK_PATTERNS = (
        re.compile(r"/video/(\d+)"),
        re.compile(r"[?&]vid=(\d+)"),
        re.compile(r"/note/(\d+)"),
        re.compile(r"modal_id=(\d+)"),
    )
    SUPPORTED_HOSTS = ("douyin.com", "iesdouyin.com")
    URL_PATTERN = re.compile(r"https?://[^\s]+")
    IMAGE_AWEME_TYPES = {2, 68, 150}
    DETAIL_ENDPOINT = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
    COOKIE_CHALLENGE_URL_KEYWORDS = ("passport", "login", "verify", "captcha")
    COOKIE_CHALLENGE_TEXT_KEYWORDS = ("登录", "验证码", "验证", "访问过于频繁", "风控", "安全验证", "请先登录")
    RETRYABLE_FILTER_REASON_KEYWORDS = ("login", "verify", "captcha", "risk", "freq", "limit")
    RETRYABLE_FILTER_MESSAGE_KEYWORDS = ("登录", "验证码", "验证", "频繁", "风控", "限制", "稍后再试")

    def __init__(
        self,
        base_url: str = "",
        timeout_seconds: int = 30,
        http_client: httpx.AsyncClient | None = None,
        user_state_store: UserStateStore | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._user_state_store = user_state_store or UserStateStore()

    async def parse_video(self, url: str) -> ParseResult:
        state = self._user_state_store.load()
        if not state.has_cookie:
            raise ParserCookieRequiredError(COOKIE_REQUIRED_MESSAGE)

        close_client = False
        client = self._http_client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout_seconds)
            close_client = True

        try:
            aweme_id = await self._resolve_aweme_id(url, cookie=state.douyin_cookie, client=client)
            detail = await self._fetch_aweme_detail(aweme_id=aweme_id, cookie=state.douyin_cookie, client=client)

            if self._is_image_post(detail):
                raise ParserUnsupportedContentError(UNSUPPORTED_IMAGE_MESSAGE)

            video_data = detail.get("video")
            if not isinstance(video_data, dict):
                raise ParserRetryableError("解析结果缺少 video 字段")

            video_url = self.select_video_url(video_data)
            return ParseResult(
                aweme_id=str(detail.get("aweme_id") or aweme_id).strip() or aweme_id,
                video_url=video_url,
                raw_data=detail,
            )
        except httpx.TimeoutException as exc:
            raise ParserCookieRetryableError(f"解析请求超时: {COOKIE_RETRY_HINT}") from exc
        except httpx.HTTPError as exc:
            raise ParserRetryableError(f"解析请求异常: {exc}") from exc
        except ValueError as exc:
            raise ParserRetryableError(f"解析 JSON 失败: {exc}") from exc
        finally:
            if close_client:
                await client.aclose()

    def select_video_url(self, video_data: dict[str, Any]) -> str:
        bit_rate_list = video_data.get("bit_rate")
        candidates: list[tuple[int, int, str]] = []

        if isinstance(bit_rate_list, list):
            for item in bit_rate_list:
                if not isinstance(item, dict):
                    continue
                is_h265 = int(item.get("is_h265", 0))
                if is_h265 != 0:
                    continue

                item_mime = str(item.get("mime_type", "")).lower().strip()
                if item_mime and not item_mime.startswith("video/"):
                    continue

                play_addr = item.get("play_addr") if isinstance(item.get("play_addr"), dict) else {}
                addr_mime = str(play_addr.get("mime_type", "") or play_addr.get("data_type", "")).lower().strip()
                if addr_mime and not addr_mime.startswith("video/"):
                    continue

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
                candidate_url = self._pick_preferred_url_from_list(url_list)
                if not candidate_url:
                    continue
                try:
                    bitrate = int(item.get("bit_rate", 0))
                except (TypeError, ValueError):
                    bitrate = 0
                domain_priority = self._url_domain_priority(candidate_url)
                candidates.append((domain_priority, bitrate, candidate_url))

        if candidates:
            candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
            return candidates[0][2]

        fallback_h264 = self._pick_url(video_data.get("play_addr_h264"))
        if fallback_h264:
            return fallback_h264

        fallback_play = self._pick_url(video_data.get("play_addr"))
        if fallback_play:
            return fallback_play

        raise ParserRetryableError("无法从解析结果中提取可用视频直链")

    async def health_check(self) -> tuple[bool, str]:
        state = self._user_state_store.load()
        if state.has_cookie:
            return True, "已保存 Cookie（未验证）"
        return False, "未配置 Cookie"

    async def _resolve_aweme_id(self, url: str, cookie: str, client: httpx.AsyncClient) -> str:
        extracted_url = self._extract_url(url)
        if not extracted_url:
            raise ParserClientSideError("输入中未找到有效抖音链接")

        try:
            response = await client.get(
                extracted_url,
                headers=self._build_headers(cookie=cookie),
                follow_redirects=True,
            )
        except httpx.TimeoutException as exc:
            raise ParserCookieRetryableError(f"解析短链超时: {COOKIE_RETRY_HINT}") from exc

        if response.status_code in self.RETRYABLE_STATUS:
            raise ParserCookieRetryableError(COOKIE_RETRY_HINT)
        if response.status_code >= 400:
            raise ParserClientSideError(f"解析链接失败（HTTP {response.status_code}）")

        final_url = str(response.url)
        aweme_id = self._extract_aweme_id_from_url(final_url)
        if aweme_id:
            return aweme_id
        if self._looks_like_cookie_challenge(final_url, response.text):
            raise ParserCookieRetryableError(COOKIE_RETRY_HINT)
        raise ParserClientSideError("无法从链接中提取抖音 aweme_id")

    async def _fetch_aweme_detail(
        self,
        aweme_id: str,
        cookie: str,
        client: httpx.AsyncClient,
    ) -> dict[str, Any]:
        params = self._build_detail_params(aweme_id)
        query_string = urlencode(params)
        xbogus = XBogus(DEFAULT_DOUYIN_USER_AGENT).get_xbogus(query_string)
        response = await client.get(
            f"{self.DETAIL_ENDPOINT}?{query_string}&X-Bogus={xbogus}",
            headers=self._build_headers(cookie=cookie),
            follow_redirects=True,
        )

        if response.status_code in self.RETRYABLE_STATUS:
            raise ParserCookieRetryableError(COOKIE_RETRY_HINT)
        if response.status_code >= 400:
            raise ParserError(f"抖音详情请求失败（HTTP {response.status_code}）")

        payload = response.json()
        if not isinstance(payload, dict):
            raise ParserRetryableError("解析结果为空或格式错误")

        detail = payload.get("aweme_detail")
        if isinstance(detail, dict):
            return detail

        filter_detail = payload.get("filter_detail")
        if isinstance(filter_detail, dict):
            filter_reason = str(filter_detail.get("filter_reason") or "").strip().lower()
            detail_msg = str(filter_detail.get("detail_msg") or "").strip()
            if self._is_retryable_filter_detail(filter_reason, detail_msg):
                raise ParserCookieRetryableError(COOKIE_RETRY_HINT)
            if detail_msg:
                raise ParserClientSideError(f"作品不可访问: {detail_msg}")

        raise ParserRetryableError("解析结果为空或格式错误")

    @classmethod
    def _looks_like_cookie_challenge(cls, final_url: str, response_text: str) -> bool:
        lowered_url = (final_url or "").lower()
        lowered_text = (response_text or "").lower()
        if any(keyword in lowered_url for keyword in cls.COOKIE_CHALLENGE_URL_KEYWORDS):
            return True
        return any(keyword.lower() in lowered_text for keyword in cls.COOKIE_CHALLENGE_TEXT_KEYWORDS)

    @classmethod
    def _is_retryable_filter_detail(cls, filter_reason: str, detail_msg: str) -> bool:
        lowered_reason = (filter_reason or "").lower()
        lowered_msg = (detail_msg or "").lower()
        if any(keyword in lowered_reason for keyword in cls.RETRYABLE_FILTER_REASON_KEYWORDS):
            return True
        return any(keyword.lower() in lowered_msg for keyword in cls.RETRYABLE_FILTER_MESSAGE_KEYWORDS)

    @staticmethod
    def _build_headers(cookie: str) -> dict[str, str]:
        headers = {
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.douyin.com/",
            "User-Agent": DEFAULT_DOUYIN_USER_AGENT,
        }
        if cookie.strip():
            headers["Cookie"] = cookie
        return headers

    @staticmethod
    def _build_detail_params(aweme_id: str) -> dict[str, str | int]:
        return {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "pc_client_type": 1,
            "version_code": "290100",
            "version_name": "29.1.0",
            "cookie_enabled": "true",
            "screen_width": 1536,
            "screen_height": 864,
            "browser_language": "zh-CN",
            "browser_platform": "MacIntel",
            "browser_name": "Chrome",
            "browser_version": "130.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "130.0.0.0",
            "os_name": "Mac OS",
            "os_version": "10.15.7",
            "cpu_core_num": 8,
            "device_memory": 8,
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "from_user_page": "1",
            "locate_query": "false",
            "need_time_list": "1",
            "pc_libra_divert": "Mac",
            "publish_video_strategy_type": "2",
            "round_trip_time": "0",
            "show_live_replay_strategy": "1",
            "time_list_query": "0",
            "whale_cut_token": "",
            "update_version_code": "170400",
            "msToken": "",
            "aweme_id": aweme_id,
        }

    def _extract_url(self, raw: str) -> str | None:
        if not isinstance(raw, str):
            return None
        match = self.URL_PATTERN.search(raw.strip())
        if not match:
            candidate = raw.strip()
            if not candidate:
                return None
            candidate = candidate if "://" in candidate else f"https://{candidate}"
            try:
                host = (httpx.URL(candidate).host or "").lower()
            except httpx.InvalidURL:
                return None
            if any(host == domain or host.endswith(f".{domain}") for domain in self.SUPPORTED_HOSTS):
                return candidate
            return None
        return match.group(0).rstrip(".,)")

    def _extract_aweme_id_from_url(self, url: str) -> str | None:
        if not isinstance(url, str):
            return None
        lowered = url.lower()
        if not any(domain in lowered for domain in self.SUPPORTED_HOSTS):
            return None
        for pattern in self.DIRECT_LINK_PATTERNS:
            match = pattern.search(url)
            if match:
                return match.group(1)
        return None

    @classmethod
    def _is_image_post(cls, detail: dict[str, Any]) -> bool:
        aweme_type = detail.get("aweme_type")
        try:
            aweme_type_int = int(aweme_type)
        except (TypeError, ValueError):
            aweme_type_int = -1
        if aweme_type_int in cls.IMAGE_AWEME_TYPES:
            return True
        if isinstance(detail.get("images"), list) and detail.get("images"):
            return True
        if isinstance(detail.get("image_post_info"), dict) and detail.get("image_post_info"):
            return True
        return False

    @staticmethod
    def _pick_url(node: Any) -> str | None:
        if not isinstance(node, dict):
            return None
        url_list = node.get("url_list")
        if isinstance(url_list, list):
            return ParserClient._pick_preferred_url_from_list(url_list)
        return None

    @staticmethod
    def _pick_preferred_url_from_list(url_list: list[Any]) -> str | None:
        urls = [str(item) for item in url_list if isinstance(item, str) and item.strip()]
        if not urls:
            return None

        for url in urls:
            lowered = url.lower()
            if "v95-" in lowered or "v95." in lowered:
                return url

        for url in urls:
            lowered = url.lower()
            if "v26-" in lowered or "v26." in lowered:
                continue
            return url

        return urls[0]

    @staticmethod
    def _url_domain_priority(url: str) -> int:
        lowered = (url or "").lower()
        if "v95-" in lowered or "v95." in lowered:
            return 2
        if "v26-" in lowered or "v26." in lowered:
            return 0
        return 1
