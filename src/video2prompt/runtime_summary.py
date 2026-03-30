"""运行摘要聚合。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .models import Task, TaskState


@dataclass(frozen=True)
class ErrorSummaryItem:
    message: str
    count: int


@dataclass(frozen=True)
class RuntimeSummary:
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    cancelled_tasks: int
    active_tasks: int
    recent_updates: list[Task]
    recent_failures: list[Task]
    error_summary: list[ErrorSummaryItem]


def build_runtime_summary(
    tasks: list[Task],
    limit_recent: int,
    limit_failures: int,
) -> RuntimeSummary:
    completed = sum(task.state == TaskState.COMPLETED for task in tasks)
    failed = sum(task.state == TaskState.FAILED for task in tasks)
    cancelled = sum(task.state == TaskState.CANCELLED for task in tasks)
    active = sum(
        task.state
        in {
            TaskState.PARSING,
            TaskState.DURATION_CHECKING,
            TaskState.INTERPRETING,
            TaskState.INTERVAL,
        }
        for task in tasks
    )
    recent_updates = sorted(
        [task for task in tasks if task.end_time is not None],
        key=lambda item: item.end_time,
        reverse=True,
    )[:limit_recent]
    recent_failures = [task for task in tasks if task.state == TaskState.FAILED][
        :limit_failures
    ]
    counts = Counter(task.error_message for task in tasks if task.error_message)
    error_summary = [
        ErrorSummaryItem(message=message, count=count)
        for message, count in counts.most_common(limit_failures)
    ]
    return RuntimeSummary(
        total_tasks=len(tasks),
        completed_tasks=completed,
        failed_tasks=failed,
        cancelled_tasks=cancelled,
        active_tasks=active,
        recent_updates=recent_updates,
        recent_failures=recent_failures,
        error_summary=error_summary,
    )
