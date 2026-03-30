"""固定并发 worker 池。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


class TaskWorkerPool:
    def __init__(self, max_workers: int):
        self.max_workers = max_workers

    async def run(
        self,
        *,
        items: list[T],
        worker: Callable[[T], Awaitable[R]],
        cancel_event: asyncio.Event | None = None,
    ) -> list[R]:
        queue: asyncio.Queue[tuple[int, T]] = asyncio.Queue()
        for index, item in enumerate(items):
            queue.put_nowait((index, item))
        results: list[R | None] = [None] * len(items)
        cancel_event = cancel_event or asyncio.Event()

        async def _consume() -> None:
            while not queue.empty() and not cancel_event.is_set():
                index, item = await queue.get()
                try:
                    results[index] = await worker(item)
                finally:
                    queue.task_done()

        await asyncio.gather(*[_consume() for _ in range(self.max_workers)])
        return [result for result in results if result is not None]
