from __future__ import annotations

import sys
from pathlib import Path

import yaml

from video2prompt.managed_parser_service import MANAGED_PARSER_PORT, ManagedParserService
from video2prompt.parser_client import ParserClient


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _create_fake_parser_tree(root: Path) -> None:
    source = root / "source"
    venv_python = root / "venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    _write_yaml(
        source / "config.yaml",
        {
            "Web": {"PyWebIO_Enable": True},
            "API": {"Host_IP": "0.0.0.0", "Host_Port": 80},
        },
    )
    _write_yaml(
        source / "crawlers" / "douyin" / "web" / "config.yaml",
        {"TokenManager": {"douyin": {"headers": {"Cookie": "old_cookie"}}}},
    )
    _write_yaml(
        source / "crawlers" / "tiktok" / "web" / "config.yaml",
        {"TokenManager": {"tiktok": {"headers": {"Cookie": "old_tiktok"}}}},
    )
    _write_yaml(
        source / "crawlers" / "tiktok" / "app" / "config.yaml",
        {"TokenManager": {"tiktok": {"headers": {"Cookie": "old_tiktok"}}}},
    )
    (source / "app").mkdir(parents=True, exist_ok=True)
    (source / "app" / "main.py").write_text("app = object()\n", encoding="utf-8")


def test_prepare_and_update_cookies(tmp_path: Path) -> None:
    parser_root = tmp_path / "managed"
    _create_fake_parser_tree(parser_root)
    service = ManagedParserService(parser_root=parser_root)

    service.prepare_managed_files(clear_cookies=True)
    service.update_cookies(douyin_cookie="douyin_cookie", tiktok_cookie="tiktok_cookie")

    config_data = yaml.safe_load(service.config_path.read_text(encoding="utf-8"))
    douyin_data = yaml.safe_load(service.douyin_cookie_config_path.read_text(encoding="utf-8"))
    tiktok_data = yaml.safe_load(service.tiktok_web_cookie_config_path.read_text(encoding="utf-8"))

    assert config_data["API"]["Host_IP"] == "127.0.0.1"
    assert config_data["API"]["Host_Port"] == MANAGED_PARSER_PORT
    assert config_data["Web"]["PyWebIO_Enable"] is False
    assert douyin_data["TokenManager"]["douyin"]["headers"]["Cookie"] == "douyin_cookie"
    assert tiktok_data["TokenManager"]["tiktok"]["headers"]["Cookie"] == "tiktok_cookie"


def test_start_stop_and_status(tmp_path: Path, monkeypatch) -> None:
    parser_root = tmp_path / "managed"
    _create_fake_parser_tree(parser_root)
    service = ManagedParserService(parser_root=parser_root)

    monkeypatch.setattr(service, "wait_until_healthy", lambda timeout_seconds: True)
    monkeypatch.setattr(service, "_build_start_command", lambda: [sys.executable, "-c", "import time; time.sleep(60)"])

    pid = service.start(wait_timeout=0.1)
    assert pid > 0
    assert service.is_running() is True

    monkeypatch.setattr(service, "health_check", lambda: (True, "ok"))
    status = service.read_status()
    assert status.running is True
    assert status.healthy is True

    service.stop()
    assert service.is_running() is False


def test_test_parse_surfaces_recent_parser_log_hint(tmp_path: Path, monkeypatch) -> None:
    parser_root = tmp_path / "managed"
    _create_fake_parser_tree(parser_root)
    service = ManagedParserService(parser_root=parser_root)
    service.runtime_dir.mkdir(parents=True, exist_ok=True)
    service.log_file.write_text(
        "\n".join(
            [
                "WARNING 第 1 次响应内容为空, 状态码: 200",
                "ERROR 无效响应类型。响应类型: <class 'NoneType'>",
            ]
        ),
        encoding="utf-8",
    )

    async def _fake_parse_video(self: ParserClient, url: str):  # noqa: ARG001
        raise RuntimeError("解析请求超时:")

    monkeypatch.setattr(ParserClient, "parse_video", _fake_parse_video)

    ok, message = service.test_parse("https://www.douyin.com/video/123")

    assert ok is False
    assert "抖音详情接口返回 200 但响应内容为空" in message
