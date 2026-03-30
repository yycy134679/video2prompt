"""macOS 打包产物冒烟检查。"""

from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from pathlib import Path


def _resolve_app_executable(app_path: Path) -> Path:
    return app_path / "Contents" / "MacOS" / "video2prompt"


def _read_url(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=1) as response:
        body = response.read().decode(errors="ignore")
        return response.status, body


def _homepage_ready(body: str) -> bool:
    normalized = body.lower()
    return "streamlit" in normalized or "video2prompt" in normalized


def wait_for_healthcheck(app_path: Path) -> bool:
    executable = _resolve_app_executable(app_path)
    port = int(os.environ.get("VIDEO2PROMPT_SMOKE_TEST_PORT", "8516"))
    env = dict(os.environ)
    env["VIDEO2PROMPT_DESKTOP_SERVER"] = "1"
    env["VIDEO2PROMPT_STREAMLIT_PORT"] = str(port)
    process = subprocess.Popen(
        [str(executable)],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    healthcheck_url = f"http://127.0.0.1:{port}/_stcore/health"
    homepage_url = f"http://127.0.0.1:{port}/"
    deadline = time.time() + 20.0
    try:
        while time.time() < deadline:
            try:
                status, body = _read_url(healthcheck_url)
                if status == 200 and body.strip().lower() == "ok":
                    homepage_status, homepage_body = _read_url(homepage_url)
                    if homepage_status == 200 and _homepage_ready(homepage_body):
                        return True
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        return False
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def smoke_test_app(app_path: Path) -> int:
    executable = _resolve_app_executable(app_path)
    if not app_path.exists() or not executable.exists():
        return 1
    if not wait_for_healthcheck(app_path):
        return 1
    print("ok")
    return 0
