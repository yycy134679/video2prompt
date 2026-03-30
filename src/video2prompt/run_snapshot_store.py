"""运行快照读写。"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Task, TaskState


class RunSnapshotStore:
    def __init__(self, snapshot_path: Path):
        self.snapshot_path = snapshot_path

    def save(self, tasks: list[Task]) -> None:
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "pid": task.pid,
                "original_link": task.original_link,
                "category": task.category,
                "state": task.state.value,
                "error_message": task.error_message,
            }
            for task in tasks
        ]
        self.snapshot_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_remaining_tasks(self) -> list[Task]:
        if not self.snapshot_path.exists():
            return []
        raw = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        tasks = [
            Task(
                pid=item["pid"],
                original_link=item["original_link"],
                category=item.get("category", ""),
                state=TaskState(item["state"]),
                error_message=item.get("error_message", ""),
            )
            for item in raw
        ]
        return [task for task in tasks if task.state not in {TaskState.COMPLETED}]
