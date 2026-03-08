"""受管 Douyin/TikTok 解析服务。"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError
from .parser_client import ParserClient

PARSER_RELEASE_TAG = "V4.1.2"
MANAGED_PARSER_HOST = "127.0.0.1"
MANAGED_PARSER_PORT = 18080


@dataclass
class ManagedParserStatus:
    installed: bool
    running: bool
    healthy: bool
    pid: int | None
    base_url: str
    parser_root: str
    source_dir: str
    config_path: str
    log_path: str
    douyin_cookie_configured: bool
    tiktok_cookie_configured: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ManagedParserService:
    """管理本地受控的 Douyin_TikTok_Download_API 服务。"""

    def __init__(
        self,
        repo_root: str | Path | None = None,
        parser_root: str | Path | None = None,
        host: str = MANAGED_PARSER_HOST,
        port: int = MANAGED_PARSER_PORT,
    ) -> None:
        base_root = Path(repo_root or Path.cwd()).resolve()
        self.repo_root = base_root
        self.parser_root = Path(parser_root or (base_root / ".managed" / "douyin_tiktok_download_api")).resolve()
        self.host = host
        self.port = int(port)

        self.source_dir = self.parser_root / "source"
        self.venv_dir = self.parser_root / "venv"
        self.runtime_dir = self.parser_root / "runtime"
        self.downloads_dir = self.parser_root / "downloads"
        self.pid_file = self.runtime_dir / "parser.pid"
        self.log_file = self.runtime_dir / "parser.log"
        self.config_path = self.source_dir / "config.yaml"
        self.douyin_cookie_config_path = self.source_dir / "crawlers" / "douyin" / "web" / "config.yaml"
        self.tiktok_web_cookie_config_path = self.source_dir / "crawlers" / "tiktok" / "web" / "config.yaml"
        self.tiktok_app_cookie_config_path = self.source_dir / "crawlers" / "tiktok" / "app" / "config.yaml"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def venv_python(self) -> Path:
        return self.venv_dir / "bin" / "python"

    def ensure_layout(self) -> None:
        self.parser_root.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

    def is_installed(self) -> bool:
        return self.config_path.exists() and self.venv_python.exists()

    def prepare_managed_files(self, clear_cookies: bool = False) -> None:
        self.ensure_layout()
        if not self.is_installed():
            raise ConfigError("未检测到受管解析服务，请先运行 scripts/mac/安装.command")

        self._set_yaml_values(
            self.config_path,
            {
                "API.Host_IP": self.host,
                "API.Host_Port": self.port,
                "Web.PyWebIO_Enable": False,
            },
        )
        if clear_cookies:
            self.update_cookies(douyin_cookie="", tiktok_cookie="")

    def update_cookies(self, douyin_cookie: str | None = None, tiktok_cookie: str | None = None) -> None:
        if not self.is_installed():
            raise ConfigError("未检测到受管解析服务，请先运行 scripts/mac/安装.command")

        if douyin_cookie is not None:
            self._set_yaml_values(
                self.douyin_cookie_config_path,
                {"TokenManager.douyin.headers.Cookie": douyin_cookie.strip()},
            )
        if tiktok_cookie is not None:
            paths = [self.tiktok_web_cookie_config_path, self.tiktok_app_cookie_config_path]
            for path in paths:
                if path.exists():
                    self._set_yaml_values(
                        path,
                        {"TokenManager.tiktok.headers.Cookie": tiktok_cookie.strip()},
                    )

    def read_status(self) -> ManagedParserStatus:
        installed = self.is_installed()
        running = self.is_running()
        healthy = False
        if running:
            healthy, _ = self.health_check()

        return ManagedParserStatus(
            installed=installed,
            running=running,
            healthy=healthy,
            pid=self._read_pid(),
            base_url=self.base_url,
            parser_root=str(self.parser_root),
            source_dir=str(self.source_dir),
            config_path=str(self.config_path),
            log_path=str(self.log_file),
            douyin_cookie_configured=self._cookie_is_configured(self.douyin_cookie_config_path),
            tiktok_cookie_configured=(
                self._cookie_is_configured(self.tiktok_web_cookie_config_path)
                or self._cookie_is_configured(self.tiktok_app_cookie_config_path)
            ),
        )

    def is_running(self) -> bool:
        pid = self._read_pid()
        if pid is None:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            self.pid_file.unlink(missing_ok=True)
            return False
        return True

    def start(self, wait_timeout: float = 20.0) -> int:
        self.prepare_managed_files(clear_cookies=False)
        if self.is_running():
            pid = self._read_pid()
            if pid is not None:
                ok, _ = self.health_check()
                if ok:
                    return pid
            self.stop()

        self.ensure_layout()
        command = self._build_start_command()
        with self.log_file.open("ab") as log_handle:
            process = subprocess.Popen(  # noqa: S603
                command,
                cwd=str(self.source_dir),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self.pid_file.write_text(str(process.pid), encoding="utf-8")

        if not self.wait_until_healthy(timeout_seconds=wait_timeout):
            self.stop()
            raise ConfigError("解析服务启动后未在限定时间内就绪，请检查 logs 或 parser.log")
        return process.pid

    def stop(self) -> None:
        pid = self._read_pid()
        if pid is None:
            self.pid_file.unlink(missing_ok=True)
            return
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            os.kill(pid, signal.SIGTERM)

        deadline = time.time() + 5
        while time.time() < deadline:
            if not self.is_running():
                break
            time.sleep(0.2)
        if self.is_running():
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                os.kill(pid, signal.SIGKILL)
        self.pid_file.unlink(missing_ok=True)

    def wait_until_healthy(self, timeout_seconds: float = 20.0) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            ok, _ = self.health_check()
            if ok:
                return True
            if not self.is_running():
                return False
            time.sleep(0.5)
        return False

    def health_check(self) -> tuple[bool, str]:
        checker = ParserClient(base_url=self.base_url, timeout_seconds=5)
        return asyncio.run(checker.health_check())

    def test_parse(self, url: str) -> tuple[bool, str]:
        async def _run() -> tuple[bool, str]:
            client = ParserClient(base_url=self.base_url, timeout_seconds=15)
            try:
                result = await client.parse_video(url)
            except Exception as exc:  # noqa: BLE001
                return False, str(exc)
            return True, f"解析成功：aweme_id={result.aweme_id}，video_url={result.video_url[:120]}"

        return asyncio.run(_run())

    def _build_start_command(self) -> list[str]:
        if not self.venv_python.exists():
            raise ConfigError("未检测到解析服务虚拟环境，请先运行 scripts/mac/安装.command")
        return [
            str(self.venv_python),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            self.host,
            "--port",
            str(self.port),
        ]

    def _read_pid(self) -> int | None:
        if not self.pid_file.exists():
            return None
        try:
            return int(self.pid_file.read_text(encoding="utf-8").strip())
        except (TypeError, ValueError):
            self.pid_file.unlink(missing_ok=True)
            return None

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ConfigError(f"YAML 文件格式无效: {path}")
        return data

    @staticmethod
    def _set_dotted_value(target: dict[str, Any], dotted_key: str, value: Any) -> None:
        keys = dotted_key.split(".")
        node = target
        for key in keys[:-1]:
            child = node.get(key)
            if not isinstance(child, dict):
                child = {}
                node[key] = child
            node = child
        node[keys[-1]] = value

    def _set_yaml_values(self, path: Path, mapping: dict[str, Any]) -> None:
        data = self._load_yaml(path)
        for key, value in mapping.items():
            self._set_dotted_value(data, key, value)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    def _cookie_is_configured(self, path: Path) -> bool:
        if not path.exists():
            return False
        data = self._load_yaml(path)
        value = (
            data.get("TokenManager", {})
            .get("douyin", {})
            .get("headers", {})
            .get("Cookie")
        )
        if value is None:
            value = (
                data.get("TokenManager", {})
                .get("tiktok", {})
                .get("headers", {})
                .get("Cookie")
            )
        return bool(str(value or "").strip())
