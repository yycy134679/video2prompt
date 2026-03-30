from __future__ import annotations

from video2prompt.models import Task, TaskState
from video2prompt.run_export_payload import filter_exportable_tasks


def test_filter_exportable_tasks_only_keeps_completed_items() -> None:
    tasks = [
        Task(pid="1", original_link="a", state=TaskState.COMPLETED),
        Task(pid="2", original_link="b", state=TaskState.CANCELLED),
        Task(pid="3", original_link="c", state=TaskState.FAILED),
    ]

    exportable = filter_exportable_tasks(tasks, allow_partial=True)

    assert [task.pid for task in exportable] == ["1"]


def test_filter_exportable_tasks_keeps_all_tasks_for_full_export() -> None:
    tasks = [
        Task(pid="1", original_link="a", state=TaskState.COMPLETED),
        Task(pid="2", original_link="b", state=TaskState.FAILED),
    ]

    exportable = filter_exportable_tasks(tasks, allow_partial=False)

    assert [task.pid for task in exportable] == ["1", "2"]
