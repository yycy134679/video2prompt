"""macOS 桌面入口。"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable, Mapping

import httpx

from streamlit.web.bootstrap import load_config_options, run as streamlit_bootstrap_run

from video2prompt.runtime_paths import RuntimePaths, build_runtime_paths

APP_PORT = 8501
APP_NAME = "video2prompt"


def resolve_app_path(paths: RuntimePaths) -> Path:
    return paths.resource_root / "app.py"


def build_runtime_env(
    paths: RuntimePaths,
    existing_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source_env = dict(existing_env or os.environ)
    current_path = source_env.get("PATH", "")
    source_env["PATH"] = (
        f"{paths.binaries_dir}{os.pathsep}{current_path}" if current_path else str(paths.binaries_dir)
    )
    source_env["VIDEO2PROMPT_RESOURCE_ROOT"] = str(paths.resource_root)
    source_env["VIDEO2PROMPT_APP_SUPPORT_DIR"] = str(paths.app_support_dir)
    source_env["VIDEO2PROMPT_ENV_PATH"] = str(paths.app_support_dir / ".env")
    source_env["VIDEO2PROMPT_CONFIG_PATH"] = str(paths.app_support_dir / "config.yaml")
    source_env["VIDEO2PROMPT_FFPROBE_PATH"] = str(paths.binaries_dir / "ffprobe")
    source_env["VIDEO2PROMPT_STREAMLIT_PORT"] = str(APP_PORT)
    return source_env


def prepare_user_runtime(paths: RuntimePaths) -> None:
    paths.app_support_dir.mkdir(parents=True, exist_ok=True)
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    paths.exports_dir.mkdir(parents=True, exist_ok=True)

    config_target = paths.app_support_dir / "config.yaml"
    if not config_target.exists():
        config_target.write_text((paths.resource_root / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")

    env_target = paths.app_support_dir / ".env"
    if not env_target.exists():
        env_target.write_text((paths.resource_root / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")


def build_streamlit_flag_options() -> dict[str, Any]:
    return {
        "server.port": APP_PORT,
        "global.developmentMode": False,
    }


def build_app_url(port: int = APP_PORT) -> str:
    return f"http://127.0.0.1:{port}/"


def build_healthcheck_url(port: int = APP_PORT) -> str:
    return f"http://127.0.0.1:{port}/_stcore/health"


def list_listening_processes(
    port: int = APP_PORT,
    run_func: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[tuple[int, str]]:
    result = run_func(
        ["lsof", f"-iTCP:{port}", "-sTCP:LISTEN", "-nP", "-Fpc"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 1:
        return []
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "lsof 执行失败"
        raise RuntimeError(f"检查端口 {port} 失败: {message}")

    listeners: list[tuple[int, str]] = []
    current_pid: int | None = None
    current_command = ""
    for raw_line in result.stdout.splitlines():
        if not raw_line:
            continue
        marker = raw_line[0]
        value = raw_line[1:]
        if marker == "p":
            if current_pid is not None:
                listeners.append((current_pid, current_command))
            current_pid = int(value)
            current_command = ""
        elif marker == "c":
            current_command = value
    if current_pid is not None:
        listeners.append((current_pid, current_command))
    return listeners


def handle_running_instance(
    port: int = APP_PORT,
    listeners_func: Callable[[int], list[tuple[int, str]]] = list_listening_processes,
    open_browser_func: Callable[[str], Any] = webbrowser.open,
    app_name: str = APP_NAME,
) -> bool:
    listeners = listeners_func(port)
    if not listeners:
        return False

    if any(app_name in command for _, command in listeners):
        open_browser_func(build_app_url(port))
        return True

    listener_summary = ", ".join(f"{command or 'unknown'}({pid})" for pid, command in listeners)
    raise RuntimeError(f"端口 {port} 已被其他进程占用: {listener_summary}")


def launch_streamlit_app(
    paths: RuntimePaths,
    run_func: Callable[[str, bool, list[str], dict[str, Any]], None] = streamlit_bootstrap_run,
    load_config_func: Callable[[dict[str, Any]], None] = load_config_options,
) -> None:
    flag_options = build_streamlit_flag_options()
    load_config_func(flag_options)
    run_func(
        str(resolve_app_path(paths)),
        False,
        [],
        flag_options,
    )


def spawn_streamlit_server(
    paths: RuntimePaths,
    env: Mapping[str, str],
    popen_func: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
) -> None:
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.extend(["-m", "video2prompt.desktop_entry"])

    child_env = dict(env)
    child_env["VIDEO2PROMPT_DESKTOP_SERVER"] = "1"

    popen_func(
        command,
        env=child_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(paths.resource_root),
    )


def wait_for_server_ready(
    port: int = APP_PORT,
    timeout_seconds: float = 15.0,
    sleep_seconds: float = 0.25,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    url = build_healthcheck_url(port)
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=1.0)
            if response.status_code == 200 and response.text.strip().lower() == "ok":
                return
            last_error = f"healthcheck returned {response.status_code}: {response.text.strip()}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(sleep_seconds)
    raise RuntimeError(f"等待本地服务启动超时: {last_error or '未知错误'}")


def launch(
    paths: RuntimePaths | None = None,
    prepare_func: Callable[[RuntimePaths], None] = prepare_user_runtime,
    env_builder: Callable[[RuntimePaths, Mapping[str, str] | None], dict[str, str]] = build_runtime_env,
    instance_handler: Callable[[int], bool] = handle_running_instance,
    server_launcher: Callable[[RuntimePaths, Mapping[str, str]], None] = spawn_streamlit_server,
    wait_for_ready_func: Callable[[int], None] = wait_for_server_ready,
    open_browser_func: Callable[[str], Any] = webbrowser.open,
) -> None:
    runtime_paths = paths or build_runtime_paths()
    prepare_func(runtime_paths)
    runtime_env = env_builder(runtime_paths, os.environ)
    os.environ.update(runtime_env)
    if instance_handler(APP_PORT):
        return
    server_launcher(runtime_paths, runtime_env)
    wait_for_ready_func(APP_PORT)
    open_browser_func(build_app_url(APP_PORT))


def run_streamlit_server(
    paths: RuntimePaths | None = None,
    prepare_func: Callable[[RuntimePaths], None] = prepare_user_runtime,
    env_builder: Callable[[RuntimePaths, Mapping[str, str] | None], dict[str, str]] = build_runtime_env,
    launch_func: Callable[[RuntimePaths], None] = launch_streamlit_app,
) -> None:
    runtime_paths = paths or build_runtime_paths()
    prepare_func(runtime_paths)
    os.environ.update(env_builder(runtime_paths, os.environ))
    launch_func(runtime_paths)


def main() -> int:
    if os.environ.get("VIDEO2PROMPT_DESKTOP_ENTRY_NOOP") == "1":
        return 0
    if os.environ.get("VIDEO2PROMPT_DESKTOP_SERVER") == "1":
        run_streamlit_server()
        return 0
    launch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
