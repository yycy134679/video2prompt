from __future__ import annotations

import app

from app import (
    RUN_CONTROLLER_REGISTRY,
    _get_run_controller,
    _is_run_active,
    _persist_completed_run_snapshot,
    _restore_tasks_to_inputs,
    _request_stop,
    _resolve_completed_run_feedback,
    _store_run_controller,
    _sync_run_controller_state,
)
from video2prompt.models import Task, TaskState
from video2prompt.run_status import RunPhase, RunStatus
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


def test_mark_starting_sets_phase_and_total_tasks() -> None:
    status = RunStatus().mark_starting(total_tasks=5)

    assert status.phase == RunPhase.STARTING
    assert status.total_tasks == 5


def test_mark_stopping_keeps_completed_counts() -> None:
    status = RunStatus(total_tasks=10, completed_tasks=3).mark_stopping(active_tasks=2)

    assert status.phase == RunPhase.STOPPING
    assert status.completed_tasks == 3
    assert status.active_tasks == 2


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


def test_persist_completed_run_snapshot_keeps_completion_status_flags() -> None:
    session_state: dict[str, object] = {}
    controller = _build_controller(state=TaskState.COMPLETED)
    controller.finished = True
    controller.cancelled = False
    controller.error_message = ""

    _persist_completed_run_snapshot(controller, session_state)

    assert session_state["last_run_finished"] is True
    assert session_state["last_run_cancelled"] is False
    assert session_state["last_run_error_message"] == ""


def test_resolve_completed_run_feedback_returns_success_for_finished_snapshot() -> None:
    session_state = {
        "last_tasks": [
            Task(pid="1", original_link="https://example.com", state=TaskState.COMPLETED)
        ],
        "last_run_finished": True,
        "last_run_cancelled": False,
        "last_run_error_message": "",
    }

    assert _resolve_completed_run_feedback(session_state) == ("success", "任务执行完成")


def test_request_stop_marks_status_as_stopping() -> None:
    controller = _build_controller()
    controller.running = True
    controller.status = RunStatus(total_tasks=5, completed_tasks=1).mark_running(
        active_tasks=2
    )

    _request_stop(controller)

    assert controller.stop_requested is True
    assert controller.status.phase == RunPhase.STOPPING
    assert controller.status.completed_tasks == 1
    assert controller.status.active_tasks == 2


def test_is_run_active_treats_starting_phase_as_active() -> None:
    controller = _build_controller()
    controller.status = RunStatus().mark_starting(total_tasks=1)

    assert _is_run_active(controller) is True


def test_sync_run_controller_state_reports_transition_when_thread_completes() -> None:
    class DeadThread:
        def is_alive(self) -> bool:
            return False

    session_state: dict[str, object] = {}
    controller = _build_controller(state=TaskState.COMPLETED)
    controller.thread = DeadThread()
    _store_run_controller(controller, session_state)

    transitioned = _sync_run_controller_state(controller, session_state)

    assert transitioned is True
    assert session_state["last_run_finished"] is True


def test_sync_run_controller_state_marks_status_completed_when_thread_completes() -> None:
    class DeadThread:
        def is_alive(self) -> bool:
            return False

    session_state: dict[str, object] = {}
    controller = _build_controller(state=TaskState.COMPLETED)
    controller.running = True
    controller.finished = False
    controller.thread = DeadThread()
    controller.status = RunStatus(total_tasks=1).mark_running(active_tasks=1)

    transitioned = _sync_run_controller_state(controller, session_state)

    assert transitioned is True
    assert controller.status.phase == RunPhase.COMPLETED
    assert controller.status.completed_tasks == 1
    assert controller.status.active_tasks == 0


def test_restore_tasks_to_inputs_writes_pid_and_link_values() -> None:
    session_state: dict[str, object] = {}
    tasks = [
        Task(pid="1", original_link="https://a.example"),
        Task(pid="2", original_link="https://b.example"),
    ]

    _restore_tasks_to_inputs(tasks, session_state)

    assert session_state["pid_text_input"] == "1\n2"
    assert session_state["link_text_input"] == "https://a.example\nhttps://b.example"
