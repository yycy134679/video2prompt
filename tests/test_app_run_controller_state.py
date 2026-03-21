from __future__ import annotations

import app

from app import (
    RUN_CONTROLLER_REGISTRY,
    _get_run_controller,
    _persist_completed_run_snapshot,
    _store_run_controller,
)
from video2prompt.models import Task, TaskState
from app import RunController


def _build_controller(state: TaskState = TaskState.WAITING) -> RunController:
    return RunController(
        tasks=[Task(pid="1", original_link="https://example.com", state=state)],
        show_category=False,
        is_duration_mode=False,
        app_mode_value="视频复刻提示词",
        default_user_prompt="prompt",
        output_format="plain_text",
        running=False,
        finished=True,
    )


def setup_function() -> None:
    RUN_CONTROLLER_REGISTRY.clear()


def test_store_and_get_run_controller_returns_live_object() -> None:
    session_state: dict[str, object] = {}
    controller = _build_controller()

    _store_run_controller(controller, session_state)
    controller.tasks[0].state = TaskState.COMPLETED

    retrieved = _get_run_controller(session_state)

    assert retrieved is controller
    assert retrieved is not None
    assert retrieved.tasks[0].state == TaskState.COMPLETED


def test_get_run_controller_survives_module_registry_reinitialization() -> None:
    session_state: dict[str, object] = {}
    controller = _build_controller()

    _store_run_controller(controller, session_state)

    original_registry = app.RUN_CONTROLLER_REGISTRY
    app.RUN_CONTROLLER_REGISTRY = {}
    try:
        retrieved = _get_run_controller(session_state)
    finally:
        app.RUN_CONTROLLER_REGISTRY = original_registry

    assert retrieved is controller


def test_persist_completed_run_snapshot_overwrites_waiting_tasks() -> None:
    session_state: dict[str, object] = {
        "last_tasks": [
            Task(pid="1", original_link="https://example.com", state=TaskState.WAITING)
        ],
        "last_app_mode": "旧模式",
        "last_default_user_prompt": "旧 prompt",
        "last_output_format": "json",
    }
    controller = _build_controller(state=TaskState.COMPLETED)

    _persist_completed_run_snapshot(controller, session_state)

    last_tasks = session_state["last_tasks"]
    assert isinstance(last_tasks, list)
    assert last_tasks[0].state == TaskState.COMPLETED
    assert session_state["last_app_mode"] == controller.app_mode_value
    assert session_state["last_default_user_prompt"] == controller.default_user_prompt
    assert session_state["last_output_format"] == controller.output_format


def test_persist_completed_run_snapshot_keeps_translation_compliance_runtime_values() -> (
    None
):
    session_state: dict[str, object] = {}
    controller = RunController(
        tasks=[
            Task(
                pid="1", original_link="https://example.com", state=TaskState.COMPLETED
            )
        ],
        show_category=False,
        is_duration_mode=False,
        app_mode_value="翻译合规判断",
        default_user_prompt="合规模板",
        output_format="json",
        running=False,
        finished=True,
    )

    _persist_completed_run_snapshot(controller, session_state)

    assert session_state["last_app_mode"] == "翻译合规判断"
    assert session_state["last_default_user_prompt"] == "合规模板"
    assert session_state["last_output_format"] == "json"
