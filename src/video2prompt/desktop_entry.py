"""macOS 桌面入口。"""

from __future__ import annotations

import os
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Callable, Mapping

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


def launch(
    paths: RuntimePaths | None = None,
    prepare_func: Callable[[RuntimePaths], None] = prepare_user_runtime,
    env_builder: Callable[[RuntimePaths, Mapping[str, str] | None], dict[str, str]] = build_runtime_env,
    instance_handler: Callable[[int], bool] = handle_running_instance,
    launch_func: Callable[[RuntimePaths], None] = launch_streamlit_app,
) -> None:
    runtime_paths = paths or build_runtime_paths()
    prepare_func(runtime_paths)
    os.environ.update(env_builder(runtime_paths, os.environ))
    if instance_handler(APP_PORT):
        return
    launch_func(runtime_paths)


def main() -> int:
    if os.environ.get("VIDEO2PROMPT_DESKTOP_ENTRY_NOOP") == "1":
        return 0
    launch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
