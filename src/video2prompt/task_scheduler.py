"""任务调度器。"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable
from datetime import datetime

from .batch_manager import BatchManager
from .cache_store import CacheStore
from .circuit_breaker import CircuitBreaker
from .errors import CircuitBreakerOpenError, GeminiError, GeminiRetryableError, ParserError, ParserRetryableError
from .models import AppConfig, Task, TaskState
from .parser_client import ParserClient
from .video_analysis_client import VideoAnalysisClient

TaskCallback = Callable[[Task], None]
CountdownCallback = Callable[[int], None]


class TaskScheduler:
    """编排解析、解读、缓存与风控节奏。"""

    def __init__(
        self,
        parser: ParserClient,
        model_client: VideoAnalysisClient,
        cache: CacheStore,
        config: AppConfig,
        parser_breaker: CircuitBreaker,
        gemini_breaker: CircuitBreaker,
        logger: logging.Logger | None = None,
    ):
        self.parser = parser
        self.model_client = model_client
        self.cache = cache
        self.config = config
        self.parser_breaker = parser_breaker
        self.gemini_breaker = gemini_breaker
        self.logger = logger or logging.getLogger("video2prompt")

        self._global_pause_until: float = 0.0
        self._pause_lock = asyncio.Lock()
        self._circuit_reason: str | None = None
        self._default_user_prompt = ""

    async def run(
        self,
        tasks: list[Task],
        user_prompt: str,
        on_update: TaskCallback | None = None,
        on_batch_countdown: CountdownCallback | None = None,
        cancel_event: asyncio.Event | None = None,
        skip_rest_event: asyncio.Event | None = None,
    ) -> None:
        if cancel_event is None:
            cancel_event = asyncio.Event()
        if skip_rest_event is None:
            skip_rest_event = asyncio.Event()

        self._default_user_prompt = user_prompt
        batch_manager = BatchManager(
            batch_size=self.config.batch.size,
            rest_min=self.config.batch.rest_min_minutes,
            rest_max=self.config.batch.rest_max_minutes,
        )

        batches = batch_manager.split_batches(tasks)
        for batch_index, batch in enumerate(batches, start=1):
            if cancel_event.is_set():
                self._mark_cancelled(batch, on_update)
                break

            for task in batch:
                task.batch_number = batch_index

            await self.run_batch(batch, on_update=on_update, cancel_event=cancel_event)

            if cancel_event.is_set():
                break
            if self._circuit_reason:
                self._mark_circuit_break(batch, on_update)
                break

            if batch_index < len(batches):
                ok = await batch_manager.wait_between_batches(
                    on_countdown=on_batch_countdown,
                    cancel_event=cancel_event,
                    skip_event=skip_rest_event,
                )
                if not ok:
                    remain_tasks = [task for remain_batch in batches[batch_index:] for task in remain_batch]
                    self._mark_cancelled(remain_tasks, on_update)
                    break

    async def run_batch(
        self,
        tasks: list[Task],
        on_update: TaskCallback | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        if cancel_event is None:
            cancel_event = asyncio.Event()

        semaphore = asyncio.Semaphore(self.config.parser.concurrency)
        coros = [self.execute_task(task, semaphore, on_update=on_update, cancel_event=cancel_event) for task in tasks]
        await asyncio.gather(*coros)

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

        try:
            if cancel_event.is_set():
                task.state = TaskState.CANCELLED
                return self._emit(task, on_update)

            self._check_circuit()
            await self._handle_cache(task, on_update)
            if task.cache_hit:
                await self._completion_delay()
                return

            await self._parse_with_retry(task, parser_semaphore, on_update, cancel_event)
            await self._model_with_retry(task, on_update, cancel_event)

            task.state = TaskState.COMPLETED
            self._emit(task, on_update)
        except CircuitBreakerOpenError as exc:
            task.state = TaskState.CIRCUIT_BREAK
            task.error_message = str(exc)
            self._emit(task, on_update)
        except Exception as exc:  # noqa: BLE001
            task.state = TaskState.FAILED
            task.error_message = str(exc)
            self.logger.exception("任务执行失败 pid=%s link=%s", task.pid, task.original_link)
            self._emit(task, on_update)
        finally:
            task.end_time = datetime.now()
            self._emit(task, on_update)
            await self._completion_delay()

    async def _handle_cache(self, task: Task, on_update: TaskCallback | None) -> None:
        link_hash = self.cache.hash_link(task.original_link)
        prompt_hash = (
            self.cache.hash_prompt(self._default_user_prompt) if self.config.cache.include_prompt_hash_in_key else "_"
        )
        cached = await self.cache.get_cached_result(link_hash=link_hash, prompt_hash=prompt_hash)
        if cached is None:
            return
        task.cache_hit = True
        task.aweme_id = cached.aweme_id
        task.video_url = cached.video_url
        task.gemini_output = cached.gemini_output
        task.fps_used = cached.fps_used
        task.state = TaskState.COMPLETED
        self._emit(task, on_update)

    async def _parse_with_retry(
        self,
        task: Task,
        parser_semaphore: asyncio.Semaphore,
        on_update: TaskCallback | None,
        cancel_event: asyncio.Event,
    ) -> None:
        backoff_seq = self.config.retry.parser_backoff_seconds
        max_attempts = len(backoff_seq) + 1
        for attempt in range(1, max_attempts + 1):
            if cancel_event.is_set():
                task.state = TaskState.CANCELLED
                self._emit(task, on_update)
                raise Exception("任务已取消")

            self._check_circuit()
            await self._wait_global_pause()
            await asyncio.sleep(random.uniform(self.config.parser.pre_delay_min_seconds, self.config.parser.pre_delay_max_seconds))

            task.state = TaskState.PARSING
            task.parse_retries = attempt - 1
            self._emit(task, on_update)
            try:
                async with parser_semaphore:
                    result = await self.parser.parse_video(task.original_link)
                self.parser_breaker.record_success()
                task.aweme_id = result.aweme_id
                task.video_url = result.video_url
                task.state = TaskState.INTERVAL
                self._emit(task, on_update)
                return
            except ParserRetryableError as exc:
                self.parser_breaker.record_failure()
                self.logger.warning("解析可重试错误: %s", exc)
                if self.parser_breaker.is_tripped():
                    self._trip_circuit("解析服务熔断")
                if attempt >= max_attempts:
                    raise ParserError(f"解析重试耗尽: {exc}") from exc
                await self._backoff_wait("parser", attempt, on_update=on_update, task=task)
            except ParserError as exc:
                # 对 4xx 这类链接/输入问题不计入熔断，避免误判为服务整体不可用。
                if self._is_parser_client_side_error(str(exc)):
                    self.logger.error("解析不可重试错误（不计入熔断）: %s", exc)
                else:
                    self.parser_breaker.record_failure()
                    self.logger.error("解析不可重试错误: %s", exc)
                    if self.parser_breaker.is_tripped():
                        self._trip_circuit("解析服务熔断")
                raise

    async def _model_with_retry(
        self,
        task: Task,
        on_update: TaskCallback | None,
        cancel_event: asyncio.Event,
    ) -> None:
        backoff_seq = self.config.retry.gemini_backoff_seconds
        max_attempts = len(backoff_seq) + 1

        for attempt in range(1, max_attempts + 1):
            if cancel_event.is_set():
                task.state = TaskState.CANCELLED
                self._emit(task, on_update)
                raise Exception("任务已取消")

            self._check_circuit()
            await self._wait_global_pause()
            task.state = TaskState.INTERPRETING
            task.gemini_retries = attempt - 1
            self._emit(task, on_update)

            try:
                output, fps_used = await self.model_client.interpret_video(
                    video_uri=task.video_url,
                    user_prompt=self._default_user_prompt,
                    fps=self.config.gemini.video_fps,
                    fps_fallback=self.config.gemini.fps_fallback,
                )
                self.gemini_breaker.record_success()
                task.gemini_output = output
                task.fps_used = fps_used

                link_hash = self.cache.hash_link(task.original_link)
                prompt_hash = (
                    self.cache.hash_prompt(self._default_user_prompt)
                    if self.config.cache.include_prompt_hash_in_key
                    else "_"
                )
                await self.cache.save_result(
                    link_hash=link_hash,
                    prompt_hash=prompt_hash,
                    aweme_id=task.aweme_id,
                    video_url=task.video_url,
                    gemini_output=task.gemini_output,
                    fps_used=task.fps_used,
                )
                return
            except GeminiRetryableError as exc:
                is_fetch_error = self.model_client.is_video_fetch_error_message(str(exc))
                if is_fetch_error:
                    self.logger.warning("模型可重试错误（视频直链访问失败，不计入熔断）: %s", exc)
                else:
                    self.gemini_breaker.record_failure()
                    self.logger.warning("模型可重试错误: %s", exc)

                # 视频直链失效时，先重新解析再试模型请求。
                if is_fetch_error:
                    self.logger.info("检测到视频资源拉取失败，尝试重新解析直链")
                    await self._reparse_video_url(task)

                if self.gemini_breaker.is_tripped():
                    self._trip_circuit("模型服务熔断")
                if attempt >= max_attempts:
                    raise GeminiError(f"模型重试耗尽: {exc}") from exc
                await self._backoff_wait("gemini", attempt, on_update=on_update, task=task)
            except GeminiError as exc:
                is_fetch_error = self.model_client.is_video_fetch_error_message(str(exc))
                if is_fetch_error:
                    self.logger.error("模型不可重试错误（视频直链访问失败，不计入熔断）: %s", exc)
                else:
                    self.gemini_breaker.record_failure()
                    self.logger.error("模型不可重试错误: %s", exc)

                if is_fetch_error:
                    try:
                        await self._reparse_video_url(task)
                    except Exception as reparse_exc:  # noqa: BLE001
                        raise GeminiError(f"模型失败，且重解析失败: {reparse_exc}") from exc
                if self.gemini_breaker.is_tripped():
                    self._trip_circuit("模型服务熔断")
                raise

    async def _reparse_video_url(self, task: Task) -> None:
        result = await self.parser.parse_video(task.original_link)
        task.aweme_id = result.aweme_id
        task.video_url = result.video_url

    async def _backoff_wait(
        self,
        service: str,
        attempt: int,
        on_update: TaskCallback | None = None,
        task: Task | None = None,
    ) -> None:
        if service == "parser":
            seq = self.config.retry.parser_backoff_seconds
            cap = self.config.retry.parser_backoff_cap_seconds
        else:
            seq = self.config.retry.gemini_backoff_seconds
            cap = self.config.retry.gemini_backoff_cap_seconds

        idx = max(0, min(attempt - 1, len(seq) - 1))
        delay = min(int(seq[idx]), int(cap))

        if self.config.retry.pause_global_queue_during_backoff:
            async with self._pause_lock:
                self._global_pause_until = max(self._global_pause_until, time.monotonic() + delay)

        if task is not None:
            task.state = TaskState.INTERVAL
            task.error_message = f"{service} 退避 {delay}s"
            self._emit(task, on_update)

        await asyncio.sleep(delay)

    async def _wait_global_pause(self) -> None:
        while True:
            async with self._pause_lock:
                remain = self._global_pause_until - time.monotonic()
            if remain <= 0:
                return
            await asyncio.sleep(min(remain, 1.0))

    def _check_circuit(self) -> None:
        if self._circuit_reason:
            raise CircuitBreakerOpenError(self._circuit_reason)

    def _trip_circuit(self, reason: str) -> None:
        self._circuit_reason = reason
        raise CircuitBreakerOpenError(reason)

    @staticmethod
    def _is_parser_client_side_error(message: str) -> bool:
        return "解析服务状态码 4" in message

    @staticmethod
    def _emit(task: Task, on_update: TaskCallback | None) -> None:
        if on_update is not None:
            on_update(task)

    def _mark_cancelled(self, tasks: list[Task], on_update: TaskCallback | None) -> None:
        for task in tasks:
            if task.state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
                continue
            task.state = TaskState.CANCELLED
            self._emit(task, on_update)

    def _mark_circuit_break(self, tasks: list[Task], on_update: TaskCallback | None) -> None:
        for task in tasks:
            if task.state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.CIRCUIT_BREAK}:
                continue
            task.state = TaskState.CIRCUIT_BREAK
            task.error_message = self._circuit_reason or "熔断停止"
            self._emit(task, on_update)

    async def _completion_delay(self) -> None:
        delay = random.uniform(
            self.config.task.completion_delay_min_seconds,
            self.config.task.completion_delay_max_seconds,
        )
        if delay > 0:
            await asyncio.sleep(delay)

    def reset_circuit(self) -> None:
        self._circuit_reason = None
        self.parser_breaker.reset()
        self.gemini_breaker.reset()
