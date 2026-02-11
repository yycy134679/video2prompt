from __future__ import annotations

from video2prompt.gemini_client import GeminiClient
from video2prompt.parser_client import ParserClient


def test_gemini_build_request_body_contains_fps() -> None:
    client = GeminiClient(
        base_url="https://api.huandutech.com",
        model="gemini-3-flash-preview",
        api_key="x",
    )
    body = client.build_request_body(
        video_uri="https://example.com/video.mp4",
        user_prompt="系统提示",
        fps=2.0,
    )

    part = body["contents"][0]["parts"][0]
    assert part["videoMetadata"]["fps"] == 2.0
    assert part["fileData"]["fileUri"] == "https://example.com/video.mp4"
    assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "high"
    assert body["generationConfig"]["mediaResolution"] == "MEDIA_RESOLUTION_MEDIUM"


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
