"""运行状态机。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class RunPhase(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class RunStatus:
    phase: RunPhase = RunPhase.IDLE
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    cancelled_tasks: int = 0
    active_tasks: int = 0

    def mark_starting(self, total_tasks: int) -> "RunStatus":
        return replace(self, phase=RunPhase.STARTING, total_tasks=total_tasks)

    def mark_running(self, active_tasks: int) -> "RunStatus":
        return replace(self, phase=RunPhase.RUNNING, active_tasks=active_tasks)

    def mark_stopping(self, active_tasks: int) -> "RunStatus":
        return replace(self, phase=RunPhase.STOPPING, active_tasks=active_tasks)

    def mark_stopped(
        self,
        *,
        completed_tasks: int,
        failed_tasks: int,
        cancelled_tasks: int,
        active_tasks: int = 0,
    ) -> "RunStatus":
        return replace(
            self,
            phase=RunPhase.STOPPED,
            completed_tasks=completed_tasks,
            failed_tasks=failed_tasks,
            cancelled_tasks=cancelled_tasks,
            active_tasks=active_tasks,
        )

    def mark_completed(
        self,
        *,
        completed_tasks: int,
        failed_tasks: int,
        cancelled_tasks: int,
        active_tasks: int = 0,
    ) -> "RunStatus":
        return replace(
            self,
            phase=RunPhase.COMPLETED,
            completed_tasks=completed_tasks,
            failed_tasks=failed_tasks,
            cancelled_tasks=cancelled_tasks,
            active_tasks=active_tasks,
        )

    def mark_failed(
        self,
        *,
        completed_tasks: int,
        failed_tasks: int,
        cancelled_tasks: int,
        active_tasks: int = 0,
    ) -> "RunStatus":
        return replace(
            self,
            phase=RunPhase.FAILED,
            completed_tasks=completed_tasks,
            failed_tasks=failed_tasks,
            cancelled_tasks=cancelled_tasks,
            active_tasks=active_tasks,
        )
