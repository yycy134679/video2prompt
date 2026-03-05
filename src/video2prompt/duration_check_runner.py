"""视频时长判断执行器。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TypeVar

from .errors import ParserError, ParserRetryableError
from .models import AppConfig, ParseResult, Task, TaskState
from .parser_client import ParserClient

TaskCallback = Callable[[Task], None]
T = TypeVar("T")


class DurationCheckRunner:
    """仅执行解析 + ffprobe 时长探测，不调用模型。"""

    SHORT_VIDEO_THRESHOLD_SECONDS = 15.0
    FFPROBE_TIMEOUT_SECONDS = 20.0
    MAX_RETRIES_PER_SERVICE = 2
    BACKOFF_HARD_CAP_SECONDS = 30.0

    def __init__(
        self,
        parser: ParserClient,
        config: AppConfig,
        logger: logging.Logger | None = None,
    ):
        self.parser = parser
        self.config = config
        self.logger = logger or logging.getLogger("video2prompt")

    async def run(
        self,
        tasks: list[Task],
        on_update: TaskCallback | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        self._ensure_ffprobe_available()
        if cancel_event is None:
            cancel_event = asyncio.Event()

        semaphore = asyncio.Semaphore(self.config.parser.concurrency)
        coros = [self.execute_task(task, semaphore, on_update=on_update, cancel_event=cancel_event) for task in tasks]
        try:
            await asyncio.gather(*coros)
        except asyncio.CancelledError:
            if not cancel_event.is_set():
                raise
        finally:
            if cancel_event.is_set():
                self._mark_cancelled(tasks, on_update)

    async def execute_task(
        self,
        task: Task,
        parser_semaphore: asyncio.Semaphore,
        on_update: TaskCallback | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        if cancel_event is None:
            cancel_event = asyncio.Event()

        if task.start_time is None:
            task.start_time = datetime.now()
        task.video_duration_seconds = None
        task.duration_check_bucket = ""

        try:
            if cancel_event.is_set():
                task.state = TaskState.CANCELLED
                self._emit(task, on_update)
                return

            result = await self._parse_with_retry(
                task=task,
                parser_semaphore=parser_semaphore,
                on_update=on_update,
                cancel_event=cancel_event,
            )
            task.aweme_id = result.aweme_id
            task.video_url = result.video_url
            task.state = TaskState.DURATION_CHECKING
            task.error_message = ""
            self._emit(task, on_update)

            duration = await self._probe_duration_seconds(result.video_url, cancel_event=cancel_event)
            task.video_duration_seconds = duration
            if duration <= self.SHORT_VIDEO_THRESHOLD_SECONDS:
                task.duration_check_bucket = "le_15"
            else:
                task.duration_check_bucket = "gt_15"
            task.state = TaskState.COMPLETED
            task.error_message = ""
            self._emit(task, on_update)
        except asyncio.CancelledError:
            task.state = TaskState.CANCELLED
            task.error_message = "任务已取消"
            task.duration_check_bucket = "failed"
            self._emit(task, on_update)
        except Exception as exc:  # noqa: BLE001
            task.state = TaskState.FAILED
            task.error_message = str(exc)
            task.duration_check_bucket = "failed"
            self.logger.exception("时长判断失败 pid=%s link=%s", task.pid, task.original_link)
            self._emit(task, on_update)
        finally:
            task.end_time = datetime.now()
            self._emit(task, on_update)
            await self._completion_delay(cancel_event=cancel_event)

    async def _parse_with_retry(
        self,
        task: Task,
        parser_semaphore: asyncio.Semaphore,
        on_update: TaskCallback | None,
        cancel_event: asyncio.Event,
    ) -> ParseResult:
        backoff_seq = self.config.retry.parser_backoff_seconds
        max_attempts = min(len(backoff_seq) + 1, self.MAX_RETRIES_PER_SERVICE + 1)

        for attempt in range(1, max_attempts + 1):
            if cancel_event.is_set():
                task.state = TaskState.CANCELLED
                self._emit(task, on_update)
                raise asyncio.CancelledError("任务已取消")

            task.parse_retries = attempt - 1
            try:
                return await self._parse_with_slot_cooldown(
                    task=task,
                    parser_semaphore=parser_semaphore,
                    on_update=on_update,
                    cancel_event=cancel_event,
                )
            except ParserRetryableError as exc:
                self.logger.warning("时长判断解析可重试错误: %s", exc)
                if attempt >= max_attempts:
                    raise ParserError(f"解析重试耗尽: {exc}") from exc
                await self._backoff_wait(attempt=attempt, task=task, on_update=on_update, cancel_event=cancel_event)
            except ParserError:
                raise

        raise ParserError("解析失败")

    async def _parse_with_slot_cooldown(
        self,
        task: Task,
        parser_semaphore: asyncio.Semaphore,
        on_update: TaskCallback | None,
        cancel_event: asyncio.Event,
    ) -> ParseResult:
        acquired = False
        try:
            await self._await_with_cancel(parser_semaphore.acquire(), cancel_event=cancel_event)
            acquired = True
            task.state = TaskState.PARSING
            self._emit(task, on_update)
            return await self._await_with_cancel(self.parser.parse_video(task.original_link), cancel_event=cancel_event)
        finally:
            if acquired:
                try:
                    cooldown_seconds = random.uniform(
                        self.config.parser.pre_delay_min_seconds,
                        self.config.parser.pre_delay_max_seconds,
                    )
                    if cooldown_seconds > 0:
                        await self._sleep_with_cancel(cooldown_seconds, cancel_event=cancel_event)
                finally:
                    parser_semaphore.release()

    async def _probe_duration_seconds(self, video_url: str, cancel_event: asyncio.Event) -> float:
        raw = await self._run_ffprobe(video_url, cancel_event=cancel_event)
        try:
            duration = float(raw)
        except ValueError as exc:
            raise RuntimeError(f"ffprobe 输出无法解析为时长: {raw!r}") from exc
        if duration <= 0:
            raise RuntimeError(f"ffprobe 返回无效时长: {duration}")
        return duration

    async def _run_ffprobe(self, video_url: str, cancel_event: asyncio.Event) -> str:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            video_url,
        ]

        def _invoke() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.FFPROBE_TIMEOUT_SECONDS,
                check=False,
            )

        try:
            completed = await self._await_with_cancel(asyncio.to_thread(_invoke), cancel_event=cancel_event)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"ffprobe 超时（>{self.FFPROBE_TIMEOUT_SECONDS:.0f}s）") from exc
        except FileNotFoundError as exc:
            raise RuntimeError("未检测到 ffprobe，请先安装 ffmpeg 并确认 ffprobe 在 PATH 中") from exc

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if completed.returncode != 0:
            detail = stderr or stdout or f"exit={completed.returncode}"
            raise RuntimeError(f"ffprobe 执行失败: {detail}")
        if not stdout:
            raise RuntimeError("ffprobe 未返回时长")
        return stdout

    async def _backoff_wait(
        self,
        attempt: int,
        task: Task | None = None,
        on_update: TaskCallback | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        base_delay = self._base_backoff_delay(attempt)
        cap = min(float(self.config.retry.parser_backoff_cap_seconds), self.BACKOFF_HARD_CAP_SECONDS)
        delay = min(base_delay, cap)
        delay_with_jitter = min(delay + random.uniform(0.0, 1.0), cap)

        if task is not None:
            task.state = TaskState.INTERVAL
            task.error_message = f"parser 退避 {delay_with_jitter:.1f}s"
            self._emit(task, on_update)

        if cancel_event is None:
            await asyncio.sleep(delay_with_jitter)
            return
        await self._sleep_with_cancel(delay_with_jitter, cancel_event=cancel_event)

    def _base_backoff_delay(self, attempt: int) -> float:
        seq = self.config.retry.parser_backoff_seconds
        cap = self.config.retry.parser_backoff_cap_seconds
        idx = max(0, min(attempt - 1, len(seq) - 1))
        return float(min(int(seq[idx]), int(cap), int(self.BACKOFF_HARD_CAP_SECONDS)))

    async def _await_with_cancel(self, awaitable: Awaitable[T], cancel_event: asyncio.Event) -> T:
        work_task = asyncio.ensure_future(awaitable)
        if cancel_event.is_set():
            work_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await work_task
            raise asyncio.CancelledError("任务已取消")

        cancel_task = asyncio.create_task(cancel_event.wait())
        try:
            done, _ = await asyncio.wait({work_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
            if work_task in done:
                return await work_task

            work_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await work_task
            raise asyncio.CancelledError("任务已取消")
        finally:
            cancel_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancel_task

    async def _sleep_with_cancel(self, seconds: float, cancel_event: asyncio.Event) -> None:
        if seconds <= 0:
            return
        await self._await_with_cancel(asyncio.sleep(seconds), cancel_event=cancel_event)

    async def _completion_delay(self, cancel_event: asyncio.Event | None = None) -> None:
        delay = random.uniform(
            self.config.task.completion_delay_min_seconds,
            self.config.task.completion_delay_max_seconds,
        )
        if delay <= 0:
            return
        if cancel_event is not None:
            if cancel_event.is_set():
                return
            try:
                await self._sleep_with_cancel(delay, cancel_event=cancel_event)
            except asyncio.CancelledError:
                return
            return
        await asyncio.sleep(delay)

    @staticmethod
    def _emit(task: Task, on_update: TaskCallback | None) -> None:
        if on_update is not None:
            on_update(task)

    def _ensure_ffprobe_available(self) -> None:
        if shutil.which("ffprobe"):
            return
        raise RuntimeError("未检测到 ffprobe，请先安装 ffmpeg 并确认 ffprobe 在 PATH 中")

    def _mark_cancelled(self, tasks: list[Task], on_update: TaskCallback | None) -> None:
        for task in tasks:
            if task.state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
                continue
            task.state = TaskState.CANCELLED
            task.duration_check_bucket = "failed"
            task.error_message = "任务已取消"
            self._emit(task, on_update)
