from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping

from video2prompt.desktop_entry import (
    APP_PORT,
    APP_PORT_SEARCH_LIMIT,
    build_runtime_env,
    build_streamlit_flag_options,
    handle_running_instance,
    build_app_url,
    choose_launch_port,
    main,
    launch,
    launch_streamlit_app,
    prepare_user_runtime,
    resolve_app_path,
    run_streamlit_server,
)
from video2prompt.runtime_paths import RuntimePaths


def make_paths(tmp_path: Path) -> RuntimePaths:
    return RuntimePaths.for_bundle(
        bundle_root=tmp_path / "bundle",
        home_dir=tmp_path / "home",
    )


def test_resolve_app_path_points_to_bundle_app_py(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)

    assert resolve_app_path(paths) == paths.resource_root / "app.py"


def test_build_runtime_env_exports_runtime_locations(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)

    env = build_runtime_env(paths, existing_env={"PATH": "/usr/bin"})

    assert env["VIDEO2PROMPT_RESOURCE_ROOT"] == str(paths.resource_root)
    assert env["VIDEO2PROMPT_APP_SUPPORT_DIR"] == str(paths.app_support_dir)
    assert env["VIDEO2PROMPT_ENV_PATH"] == str(paths.app_support_dir / ".env")
    assert env["VIDEO2PROMPT_CONFIG_PATH"] == str(paths.app_support_dir / "config.yaml")
    assert env["VIDEO2PROMPT_FFPROBE_PATH"] == str(paths.binaries_dir / "ffprobe")
    assert env["PATH"].startswith(str(paths.binaries_dir))


def test_build_runtime_env_sets_fixed_streamlit_port(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)

    env = build_runtime_env(paths, existing_env={}, port=8510)

    assert env["VIDEO2PROMPT_STREAMLIT_PORT"] == "8510"


def test_build_streamlit_flag_options_disables_dev_mode_and_pins_port() -> None:
    assert build_streamlit_flag_options(port=8510) == {
        "server.port": 8510,
        "server.headless": True,
        "global.developmentMode": False,
    }


def test_launch_streamlit_app_uses_fixed_port(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    calls: dict[str, object] = {}

    def fake_run(
        main_script_path: str,
        is_hello: bool,
        args: list[str],
        flag_options: dict[str, object],
        *,
        stop_immediately_for_testing: bool = False,
    ) -> None:
        calls["main_script_path"] = main_script_path
        calls["is_hello"] = is_hello
        calls["args"] = args
        calls["flag_options"] = flag_options
        calls["stop_immediately_for_testing"] = stop_immediately_for_testing

    os.environ["VIDEO2PROMPT_STREAMLIT_PORT"] = "8510"

    launch_streamlit_app(paths, run_func=fake_run)

    assert calls["main_script_path"] == str(paths.resource_root / "app.py")
    assert calls["is_hello"] is False
    assert calls["args"] == []
    assert calls["flag_options"] == {
        "server.port": 8510,
        "server.headless": True,
        "global.developmentMode": False,
    }


def test_launch_streamlit_app_loads_config_flags_before_starting(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    calls: list[tuple[str, object]] = []

    def fake_load_config(flag_options: dict[str, object]) -> None:
        calls.append(("load", flag_options.copy()))

    def fake_run(
        main_script_path: str,
        is_hello: bool,
        args: list[str],
        flag_options: dict[str, object],
        *,
        stop_immediately_for_testing: bool = False,
    ) -> None:
        calls.append(("run", flag_options.copy()))

    os.environ["VIDEO2PROMPT_STREAMLIT_PORT"] = "8510"

    launch_streamlit_app(paths, run_func=fake_run, load_config_func=fake_load_config)

    assert calls == [
        (
            "load",
            {
                "server.port": 8510,
                "server.headless": True,
                "global.developmentMode": False,
            },
        ),
        (
            "run",
            {
                "server.port": 8510,
                "server.headless": True,
                "global.developmentMode": False,
            },
        ),
    ]


def test_choose_launch_port_falls_back_when_primary_port_taken_by_other_process() -> None:
    checked_ports: list[int] = []

    def fake_instance_handler(port: int) -> bool:
        checked_ports.append(port)
        if port == APP_PORT:
            raise RuntimeError("端口 8501 已被其他进程占用: python3(999)")
        return False

    selected_port = choose_launch_port(instance_handler=fake_instance_handler)

    assert selected_port == APP_PORT + 1
    assert checked_ports == [APP_PORT, APP_PORT + 1]


def test_choose_launch_port_reuses_existing_app_on_fallback_port() -> None:
    checked_ports: list[int] = []

    def fake_instance_handler(port: int) -> bool:
        checked_ports.append(port)
        if port == APP_PORT:
            raise RuntimeError("端口 8501 已被其他进程占用: python3(999)")
        return True

    selected_port = choose_launch_port(instance_handler=fake_instance_handler)

    assert selected_port is None
    assert checked_ports == [APP_PORT, APP_PORT + 1]


def test_choose_launch_port_raises_when_no_port_available() -> None:
    def fake_instance_handler(port: int) -> bool:
        raise RuntimeError(f"端口 {port} 已被其他进程占用: python3({port})")

    try:
        choose_launch_port(instance_handler=fake_instance_handler)
    except RuntimeError as exc:
        assert str(APP_PORT) in str(exc)
        assert str(APP_PORT + APP_PORT_SEARCH_LIMIT - 1) in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_prepare_user_runtime_copies_config_and_bootstraps_env(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    paths.resource_root.mkdir(parents=True, exist_ok=True)
    (paths.resource_root / "config.yaml").write_text("volcengine:\n  endpoint_id: ep-test\n", encoding="utf-8")
    (paths.resource_root / ".env.example").write_text("VOLCENGINE_API_KEY=\n", encoding="utf-8")

    prepare_user_runtime(paths)

    assert (paths.app_support_dir / "config.yaml").exists()
    assert (paths.app_support_dir / ".env").exists()


def test_prepare_user_runtime_does_not_overwrite_existing_files(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    paths.resource_root.mkdir(parents=True, exist_ok=True)
    (paths.resource_root / "config.yaml").write_text("new-config\n", encoding="utf-8")
    (paths.resource_root / ".env.example").write_text("VOLCENGINE_API_KEY=\n", encoding="utf-8")
    paths.app_support_dir.mkdir(parents=True, exist_ok=True)
    (paths.app_support_dir / "config.yaml").write_text("old-config\n", encoding="utf-8")
    (paths.app_support_dir / ".env").write_text("VOLCENGINE_API_KEY=existing\n", encoding="utf-8")

    prepare_user_runtime(paths)

    assert (paths.app_support_dir / "config.yaml").read_text(encoding="utf-8") == "old-config\n"
    assert (paths.app_support_dir / ".env").read_text(encoding="utf-8") == "VOLCENGINE_API_KEY=existing\n"


def test_build_app_url_points_to_local_streamlit_port() -> None:
    assert build_app_url() == f"http://127.0.0.1:{APP_PORT}/"


def test_launch_prepares_runtime_spawns_server_waits_and_opens_browser(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    calls: list[str] = []

    def fake_prepare(runtime_paths: RuntimePaths) -> None:
        assert runtime_paths == paths
        calls.append("prepare")

    def fake_build_env(runtime_paths: RuntimePaths, existing_env=None, port=None):
        assert runtime_paths == paths
        assert port == APP_PORT + 1
        calls.append("env")
        return {"PATH": "custom", "VIDEO2PROMPT_STREAMLIT_PORT": str(APP_PORT + 1)}

    def fake_spawn(runtime_paths: RuntimePaths, env: Mapping[str, str]) -> None:
        assert runtime_paths == paths
        assert os.environ["PATH"] == "custom"
        assert env["PATH"] == "custom"
        calls.append("spawn")

    def fake_choose_port(instance_handler) -> int | None:
        calls.append("choose")
        assert instance_handler(APP_PORT) is False
        return APP_PORT + 1

    def fake_wait(port: int = APP_PORT) -> None:
        assert port == APP_PORT + 1
        calls.append("wait")

    opened_urls: list[str] = []

    launch(
        paths=paths,
        prepare_func=fake_prepare,
        env_builder=fake_build_env,
        instance_handler=lambda port: False,
        port_selector=fake_choose_port,
        server_launcher=fake_spawn,
        wait_for_ready_func=fake_wait,
        open_browser_func=opened_urls.append,
    )

    assert calls == ["prepare", "choose", "env", "spawn", "wait"]
    assert opened_urls == [f"http://127.0.0.1:{APP_PORT + 1}/"]


def test_handle_running_instance_reuses_browser_for_existing_app() -> None:
    opened_urls: list[str] = []

    handled = handle_running_instance(
        listeners_func=lambda port: [(1234, "/tmp/视频分析.app/Contents/MacOS/video2prompt")],
        open_browser_func=opened_urls.append,
        current_executable="/tmp/视频分析.app/Contents/MacOS/video2prompt",
    )

    assert handled is True
    assert opened_urls == [f"http://127.0.0.1:{APP_PORT}/"]


def test_handle_running_instance_stops_stale_app_listener_and_restarts() -> None:
    terminated_pids: list[int] = []

    handled = handle_running_instance(
        listeners_func=lambda port: [(4321, "/tmp/video2prompt.app/Contents/MacOS/video2prompt")],
        open_browser_func=lambda url: None,
        current_executable="/tmp/视频分析.app/Contents/MacOS/video2prompt",
        terminate_listener_func=terminated_pids.append,
    )

    assert handled is False
    assert terminated_pids == [4321]


def test_handle_running_instance_raises_for_other_process() -> None:
    try:
        handle_running_instance(
            listeners_func=lambda port: [(4321, "python3")],
            open_browser_func=lambda url: None,
        )
    except RuntimeError as exc:
        assert str(APP_PORT) in str(exc)
        assert "python3" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_launch_does_not_start_new_server_when_existing_instance_reused(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    calls: list[str] = []

    def fake_prepare(runtime_paths: RuntimePaths) -> None:
        assert runtime_paths == paths
        calls.append("prepare")

    def fake_build_env(runtime_paths: RuntimePaths, existing_env=None, port=None):
        assert runtime_paths == paths
        assert port is None
        calls.append("env")
        return {"PATH": "custom", "VIDEO2PROMPT_STREAMLIT_PORT": str(APP_PORT)}

    def fake_handle(port: int = APP_PORT) -> bool:
        assert port == APP_PORT
        calls.append("handle")
        return True

    def fake_spawn(runtime_paths: RuntimePaths, env: Mapping[str, str]) -> None:
        calls.append("spawn")

    def fake_wait(port: int = APP_PORT) -> None:
        calls.append("wait")

    def fake_choose_port(instance_handler) -> int | None:
        calls.append("choose")
        assert instance_handler(APP_PORT) is True
        return None

    launch(
        paths=paths,
        prepare_func=fake_prepare,
        env_builder=fake_build_env,
        instance_handler=fake_handle,
        port_selector=fake_choose_port,
        server_launcher=fake_spawn,
        wait_for_ready_func=fake_wait,
        open_browser_func=lambda url: None,
    )

    assert calls == ["prepare", "choose", "handle"]


def test_desktop_entry_can_run_as_top_level_script() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "src/video2prompt/desktop_entry.py",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": "src",
            "VIDEO2PROMPT_DESKTOP_ENTRY_NOOP": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_main_calls_launch(monkeypatch) -> None:
    calls: list[str] = []

    def fake_launch() -> None:
        calls.append("launch")

    monkeypatch.setattr("video2prompt.desktop_entry.launch", fake_launch)

    assert main() == 0
    assert calls == ["launch"]


def test_main_runs_streamlit_server_in_child_mode(monkeypatch, tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    calls: list[str] = []

    monkeypatch.setenv("VIDEO2PROMPT_DESKTOP_SERVER", "1")
    monkeypatch.setattr("video2prompt.desktop_entry.run_streamlit_server", lambda: calls.append("run_streamlit_server"))

    assert main() == 0
    assert calls == ["run_streamlit_server"]


def test_run_streamlit_server_prepares_runtime_builds_env_and_launches(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    calls: list[str] = []

    def fake_prepare(runtime_paths: RuntimePaths) -> None:
        assert runtime_paths == paths
        calls.append("prepare")

    def fake_build_env(runtime_paths: RuntimePaths, existing_env=None, port=None):
        assert runtime_paths == paths
        assert port is None
        calls.append("env")
        return {"PATH": "child-path", "VIDEO2PROMPT_STREAMLIT_PORT": str(APP_PORT)}

    def fake_launch_streamlit(runtime_paths: RuntimePaths) -> None:
        assert runtime_paths == paths
        assert os.environ["PATH"] == "child-path"
        calls.append("launch_streamlit")

    run_streamlit_server(
        paths=paths,
        prepare_func=fake_prepare,
        env_builder=fake_build_env,
        launch_func=fake_launch_streamlit,
    )

    assert calls == ["prepare", "env", "launch_streamlit"]
