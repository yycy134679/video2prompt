from __future__ import annotations

from pathlib import Path

from video2prompt.models import Task, TaskState
from video2prompt.run_snapshot_store import RunSnapshotStore


def test_run_snapshot_store_returns_only_unfinished_tasks(tmp_path: Path) -> None:
    store = RunSnapshotStore(snapshot_path=tmp_path / "last_run_result.json")
    tasks = [
        Task(pid="1", original_link="a", state=TaskState.COMPLETED),
        Task(pid="2", original_link="b", state=TaskState.FAILED),
        Task(pid="3", original_link="c", state=TaskState.WAITING),
    ]

    store.save(tasks)
    remaining = store.load_remaining_tasks()

    assert [task.pid for task in remaining] == ["2", "3"]
