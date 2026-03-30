from __future__ import annotations

from datetime import datetime, timedelta

import app

from video2prompt.models import Task, TaskState


def test_build_runtime_panel_payload_defaults_to_light_mode() -> None:
    now = datetime.now()
    tasks = [
        Task(
            pid="1",
            original_link="a",
            state=TaskState.COMPLETED,
            end_time=now - timedelta(seconds=3),
        ),
        Task(
            pid="2",
            original_link="b",
            state=TaskState.FAILED,
            error_message="parser timeout",
            end_time=now - timedelta(seconds=1),
        ),
        Task(
            pid="3",
            original_link="c",
            state=TaskState.PARSING,
            start_time=now - timedelta(seconds=2),
        ),
    ]

    payload = app._build_runtime_panel_payload(tasks, view_mode="light")

    assert payload.view_mode == "light"
    assert payload.total_tasks == 3
    assert [task.pid for task in payload.visible_tasks] == ["2", "3", "1"]


def test_build_runtime_panel_payload_keeps_all_tasks_in_full_mode() -> None:
    tasks = [
        Task(pid="1", original_link="a", state=TaskState.COMPLETED),
        Task(pid="2", original_link="b", state=TaskState.FAILED),
    ]

    payload = app._build_runtime_panel_payload(tasks, view_mode="full")

    assert payload.view_mode == "full"
    assert [task.pid for task in payload.visible_tasks] == ["1", "2"]
