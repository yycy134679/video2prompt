from __future__ import annotations

from datetime import datetime, timedelta

from video2prompt.models import Task, TaskState
from video2prompt.runtime_summary import build_runtime_summary


def test_build_runtime_summary_counts_states_and_recent_updates() -> None:
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

    summary = build_runtime_summary(tasks, limit_recent=2, limit_failures=2)

    assert summary.total_tasks == 3
    assert summary.completed_tasks == 1
    assert summary.failed_tasks == 1
    assert summary.active_tasks == 1
    assert [item.pid for item in summary.recent_updates] == ["2", "3"]


def test_build_runtime_summary_groups_common_errors() -> None:
    tasks = [
        Task(
            pid="1",
            original_link="a",
            state=TaskState.FAILED,
            error_message="parser timeout",
        ),
        Task(
            pid="2",
            original_link="b",
            state=TaskState.FAILED,
            error_message="parser timeout",
        ),
        Task(
            pid="3",
            original_link="c",
            state=TaskState.FAILED,
            error_message="model rate limit",
        ),
    ]

    summary = build_runtime_summary(tasks, limit_recent=5, limit_failures=5)

    assert [(item.message, item.count) for item in summary.error_summary] == [
        ("parser timeout", 2),
        ("model rate limit", 1),
    ]


def test_build_runtime_summary_counts_circuit_break_as_failure() -> None:
    now = datetime.now()
    tasks = [
        Task(
            pid="1",
            original_link="a",
            state=TaskState.CIRCUIT_BREAK,
            error_message="breaker open",
            end_time=now,
        )
    ]

    summary = build_runtime_summary(tasks, limit_recent=5, limit_failures=5)

    assert summary.failed_tasks == 1
    assert [item.pid for item in summary.recent_failures] == ["1"]
