from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from video2prompt.errors import (
    ParserClientSideError,
    ParserCookieRequiredError,
    ParserCookieRetryableError,
    ParserUnsupportedContentError,
)
from video2prompt.parser_client import COOKIE_RETRY_HINT, ParserClient
from video2prompt.user_state_store import UserStateStore
from video2prompt.volcengine_responses_client import VolcengineResponsesClient


def test_responses_build_request_body_contains_video_url_and_fps() -> None:
    client = VolcengineResponsesClient(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-test-model",
        api_key="x",
        reasoning_effort="high",
        max_output_tokens=256,
    )
    body = client._build_request_body(
        input_items=client._build_video_url_input(
            video_url="https://example.com/video.mp4",
            prompt="系统提示",
            fps=2.0,
        )
    )

    part = body["input"][0]["content"][0]
    assert part["fps"] == 2.0
    assert part["video_url"] == "https://example.com/video.mp4"
    assert body["reasoning"]["effort"] == "high"
    assert body["max_output_tokens"] == 256


def test_parser_select_video_url_prefers_h264_and_highest_bitrate() -> None:
    client = ParserClient(base_url="http://localhost:80")
    video_data = {
        "bit_rate": [
            {
                "is_h265": 1,
                "bit_rate": 999999,
                "play_addr": {"url_list": ["https://bad-hevc"], "height": 720},
            },
            {
                "is_h265": 0,
                "bit_rate": 600,
                "play_addr": {"url_list": ["https://ok-600"], "height": 1080},
            },
            {
                "is_h265": 0,
                "bit_rate": 700,
                "play_addr": {"url_list": ["https://ok-700"], "height": 1080},
            },
            {
                "is_h265": 0,
                "bit_rate": 800,
                "play_addr": {"url_list": ["https://too-high"], "height": 1440},
            },
        ],
        "play_addr_h264": {"url_list": ["https://fallback-h264"]},
        "play_addr": {"url_list": ["https://fallback-play"]},
    }

    assert client.select_video_url(video_data) == "https://ok-700"


def test_parser_select_video_url_fallback() -> None:
    client = ParserClient(base_url="http://localhost:80")
    video_data = {
        "bit_rate": [],
        "play_addr_h264": {"url_list": ["https://fallback-h264"]},
        "play_addr": {"url_list": ["https://fallback-play"]},
    }
    assert client.select_video_url(video_data) == "https://fallback-h264"


def test_parser_select_video_url_prefers_v95_domain() -> None:
    client = ParserClient(base_url="http://localhost:80")
    video_data = {
        "bit_rate": [
            {
                "is_h265": 0,
                "bit_rate": 1200,
                "play_addr": {"url_list": ["https://v26-web.douyinvod.com/high"], "height": 1080},
            },
            {
                "is_h265": 0,
                "bit_rate": 700,
                "play_addr": {"url_list": ["https://v95-web.douyinvod.com/mid"], "height": 1080},
            },
        ],
        "play_addr_h264": {"url_list": ["https://fallback-h264"]},
        "play_addr": {"url_list": ["https://fallback-play"]},
    }

    assert client.select_video_url(video_data) == "https://v95-web.douyinvod.com/mid"


def test_parser_pick_url_prefers_v95_in_same_url_list() -> None:
    client = ParserClient(base_url="http://localhost:80")
    video_data = {
        "bit_rate": [],
        "play_addr_h264": {
            "url_list": [
                "https://v26-web.douyinvod.com/first",
                "https://v95-web.douyinvod.com/second",
            ]
        },
        "play_addr": {"url_list": ["https://fallback-play"]},
    }

    assert client.select_video_url(video_data) == "https://v95-web.douyinvod.com/second"


class _StubAsyncClient:
    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url: str, **kwargs):  # noqa: ANN201
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected request")
        current = self.responses.pop(0)
        if isinstance(current, Exception):
            raise current
        return current


def _make_parser(tmp_path: Path, client: _StubAsyncClient, cookie: str | None = "sessionid=1") -> ParserClient:
    store = UserStateStore(tmp_path / "user_state.yaml")
    if cookie is not None:
        store.save_cookie(cookie)
    return ParserClient(http_client=client, user_state_store=store)


@pytest.mark.asyncio
async def test_parser_health_check_requires_cookie_async(tmp_path: Path) -> None:
    parser = _make_parser(tmp_path, _StubAsyncClient([]), cookie=None)

    ok, message = await parser.health_check()

    assert not ok
    assert message == "未配置 Cookie"


@pytest.mark.asyncio
async def test_parser_parse_video_supports_share_text_and_builds_xbogus_request_async(tmp_path: Path) -> None:
    short_url = "https://v.douyin.com/abcd/"
    final_url = "https://www.douyin.com/video/1234567890123456789"
    responses = [
        httpx.Response(200, request=httpx.Request("GET", final_url), text="ok"),
        httpx.Response(
            200,
            request=httpx.Request("GET", "https://www.douyin.com/aweme/v1/web/aweme/detail/"),
            json={
                "aweme_detail": {
                    "aweme_id": "1234567890123456789",
                    "aweme_type": 4,
                    "video": {
                        "bit_rate": [
                            {
                                "is_h265": 0,
                                "bit_rate": 700,
                                "play_addr": {
                                    "url_list": ["https://v95-web.douyinvod.com/play-1"],
                                    "height": 1080,
                                },
                            }
                        ]
                    },
                }
            },
        ),
    ]
    client = _StubAsyncClient(responses)
    parser = _make_parser(tmp_path, client)

    result = await parser.parse_video(f"分享文案 {short_url}")

    assert result.aweme_id == "1234567890123456789"
    assert result.video_url == "https://v95-web.douyinvod.com/play-1"
    assert client.calls[0][0] == short_url
    assert client.calls[0][1]["headers"]["Cookie"] == "sessionid=1"
    assert "X-Bogus=" in client.calls[1][0]
    assert "aweme_id=1234567890123456789" in client.calls[1][0]


@pytest.mark.asyncio
async def test_parser_parse_video_requires_cookie_before_request(tmp_path: Path) -> None:
    parser = _make_parser(tmp_path, _StubAsyncClient([]), cookie=None)

    with pytest.raises(ParserCookieRequiredError):
        await parser.parse_video("https://www.douyin.com/video/1")


@pytest.mark.asyncio
async def test_parser_parse_video_rejects_image_post(tmp_path: Path) -> None:
    responses = [
        httpx.Response(
            200,
            request=httpx.Request("GET", "https://www.douyin.com/video/1234567890123456789"),
            text="ok",
        ),
        httpx.Response(
            200,
            request=httpx.Request("GET", "https://www.douyin.com/aweme/v1/web/aweme/detail/"),
            json={
                "aweme_detail": {
                    "aweme_id": "1234567890123456789",
                    "aweme_type": 68,
                    "images": [{"url": "https://example.com/1.jpeg"}],
                }
            },
        ),
    ]
    parser = _make_parser(tmp_path, _StubAsyncClient(responses))

    with pytest.raises(ParserUnsupportedContentError):
        await parser.parse_video("https://www.douyin.com/video/1234567890123456789")


@pytest.mark.asyncio
async def test_parser_parse_video_maps_403_to_cookie_retry_hint(tmp_path: Path) -> None:
    responses = [
        httpx.Response(
            200,
            request=httpx.Request("GET", "https://www.douyin.com/video/1234567890123456789"),
            text="ok",
        ),
        httpx.Response(
            403,
            request=httpx.Request("GET", "https://www.douyin.com/aweme/v1/web/aweme/detail/"),
            text="forbidden",
        ),
    ]
    parser = _make_parser(tmp_path, _StubAsyncClient(responses))

    with pytest.raises(ParserCookieRetryableError, match=COOKIE_RETRY_HINT):
        await parser.parse_video("https://www.douyin.com/video/1234567890123456789")


@pytest.mark.asyncio
async def test_parser_parse_video_maps_timeout_to_cookie_retry_hint(tmp_path: Path) -> None:
    responses = [
        httpx.Response(
            200,
            request=httpx.Request("GET", "https://www.douyin.com/video/1234567890123456789"),
            text="ok",
        ),
        httpx.ReadTimeout("timeout"),
    ]
    parser = _make_parser(tmp_path, _StubAsyncClient(responses))

    with pytest.raises(ParserCookieRetryableError, match=COOKIE_RETRY_HINT):
        await parser.parse_video("https://www.douyin.com/video/1234567890123456789")


@pytest.mark.asyncio
async def test_parser_parse_video_maps_login_redirect_without_aweme_id_to_cookie_retry(tmp_path: Path) -> None:
    responses = [
        httpx.Response(
            200,
            request=httpx.Request("GET", "https://www.douyin.com/passport/web/login/"),
            text="请先登录后继续访问",
        ),
    ]
    parser = _make_parser(tmp_path, _StubAsyncClient(responses))

    with pytest.raises(ParserCookieRetryableError, match=COOKIE_RETRY_HINT):
        await parser.parse_video("分享文案 https://v.douyin.com/abcd/")


@pytest.mark.asyncio
async def test_parser_parse_video_maps_filter_detail_cookie_challenge_to_retryable(tmp_path: Path) -> None:
    responses = [
        httpx.Response(
            200,
            request=httpx.Request("GET", "https://www.douyin.com/video/1234567890123456789"),
            text="ok",
        ),
        httpx.Response(
            200,
            request=httpx.Request("GET", "https://www.douyin.com/aweme/v1/web/aweme/detail/"),
            json={
                "aweme_detail": None,
                "filter_detail": {
                    "filter_reason": "user_not_login",
                    "detail_msg": "访问过于频繁，请登录后继续",
                },
            },
        ),
    ]
    parser = _make_parser(tmp_path, _StubAsyncClient(responses))

    with pytest.raises(ParserCookieRetryableError, match=COOKIE_RETRY_HINT):
        await parser.parse_video("https://www.douyin.com/video/1234567890123456789")


@pytest.mark.asyncio
async def test_parser_parse_video_keeps_permanent_filter_detail_as_client_error(tmp_path: Path) -> None:
    responses = [
        httpx.Response(
            200,
            request=httpx.Request("GET", "https://www.douyin.com/video/1234567890123456789"),
            text="ok",
        ),
        httpx.Response(
            200,
            request=httpx.Request("GET", "https://www.douyin.com/aweme/v1/web/aweme/detail/"),
            json={
                "aweme_detail": None,
                "filter_detail": {
                    "filter_reason": "status_self_see",
                    "detail_msg": "因作品权限或已被删除，无法观看，去看看其他作品吧",
                },
            },
        ),
    ]
    parser = _make_parser(tmp_path, _StubAsyncClient(responses))

    with pytest.raises(ParserClientSideError, match="作品不可访问"):
        await parser.parse_video("https://www.douyin.com/video/1234567890123456789")
