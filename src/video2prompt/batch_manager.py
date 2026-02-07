"""批次管理。"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable

from .models import Task


class BatchManager:
    """按批次拆分任务并处理批次休息。"""

    def __init__(self, batch_size: int, rest_min: float, rest_max: float):
        self.batch_size = batch_size
        self.rest_min = rest_min
        self.rest_max = rest_max

    def split_batches(self, tasks: list[Task]) -> list[list[Task]]:
        return [tasks[i : i + self.batch_size] for i in range(0, len(tasks), self.batch_size)]

    async def wait_between_batches(
        self,
        on_countdown: Callable[[int], None] | None,
        cancel_event: asyncio.Event,
        skip_event: asyncio.Event,
    ) -> bool:
        """返回 True 表示正常等待完毕，False 表示取消。"""

        wait_seconds = int(random.uniform(self.rest_min * 60, self.rest_max * 60))
        for remain in range(wait_seconds, -1, -1):
            if cancel_event.is_set():
                return False
            if skip_event.is_set():
                skip_event.clear()
                return True
            if on_countdown is not None:
                on_countdown(remain)
            await asyncio.sleep(1)
        return True
