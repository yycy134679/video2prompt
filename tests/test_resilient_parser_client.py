from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from video2prompt.errors import ParserRetryableError
from video2prompt.models import ParseResult
from video2prompt.resilient_parser_client import ResilientParserClient, YtDlpParserClient


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _create_cookie_tree(root: Path) -> None:
    source = root / "source"
    venv_python = root / "venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")
    _write_yaml(source / "config.yaml", {"API": {"Host_IP": "127.0.0.1", "Host_Port": 18080}})
    _write_yaml(
        source / "crawlers" / "douyin" / "web" / "config.yaml",
        {"TokenManager": {"douyin": {"headers": {"Cookie": "sessionid=abc; sid_guard=xyz"}}}},
    )


@pytest.mark.asyncio
async def test_resilient_parser_uses_ytdlp_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parser_root = tmp_path / "managed"
    _create_cookie_tree(parser_root)
    client = ResilientParserClient(base_url="http://127.0.0.1:18080", parser_root=parser_root)

    async def _fail_primary(url: str):  # noqa: ARG001
        raise ParserRetryableError("primary failed")

    async def _success_fallback(url: str):  # noqa: ARG001
        return ParseResult(aweme_id="123", video_url="https://example.com/video.mp4", raw_data={"id": "123"})

    monkeypatch.setattr(client.primary, "parse_video", _fail_primary)
    monkeypatch.setattr(client.fallback, "parse_video", _success_fallback)

    result = await client.parse_video("https://www.douyin.com/video/123")

    assert result.aweme_id == "123"
    assert result.video_url == "https://example.com/video.mp4"


def test_build_cookie_file_uses_expected_domain(tmp_path: Path) -> None:
    parser_root = tmp_path / "managed"
    _create_cookie_tree(parser_root)
    client = YtDlpParserClient(parser_root=parser_root)

    content = client._build_cookie_file(  # noqa: SLF001
        "https://www.douyin.com/video/123",
        "sessionid=abc; sid_guard=xyz",
    )

    assert ".douyin.com" in content
    assert "sessionid" in content
    assert "sid_guard" in content
