"""运行结果导出负载。"""

from __future__ import annotations

from .models import Task, TaskState


def filter_exportable_tasks(tasks: list[Task], *, allow_partial: bool) -> list[Task]:
    if not allow_partial:
        return list(tasks)
    return [task for task in tasks if task.state == TaskState.COMPLETED]
