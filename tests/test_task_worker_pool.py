from __future__ import annotations

import asyncio

from video2prompt.task_worker_pool import TaskWorkerPool


def test_task_worker_pool_respects_max_workers() -> None:
    active = 0
    max_active = 0

    async def _worker(item: int) -> int:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return item

    async def _run() -> None:
        pool = TaskWorkerPool(max_workers=2)
        results = await pool.run(items=[1, 2, 3, 4], worker=_worker)
        assert results == [1, 2, 3, 4]

    asyncio.run(_run())

    assert max_active == 2


def test_task_worker_pool_stops_claiming_new_items_after_cancel() -> None:
    seen: list[int] = []

    async def _worker(item: int) -> int:
        seen.append(item)
        await asyncio.sleep(0.05)
        return item

    async def _run() -> None:
        cancel_event = asyncio.Event()
        pool = TaskWorkerPool(max_workers=1)
        runner = asyncio.create_task(
            pool.run(items=[1, 2, 3], worker=_worker, cancel_event=cancel_event)
        )
        await asyncio.sleep(0.02)
        cancel_event.set()
        await runner

    asyncio.run(_run())

    assert seen == [1]
