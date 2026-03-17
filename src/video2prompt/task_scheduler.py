"""任务调度器。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, TypeVar

import httpx

from .cache_store import CacheStore
from .circuit_breaker import CircuitBreaker
from .errors import (
    CircuitBreakerOpenError,
    ModelError,
    ModelRetryableError,
    ParserClientSideError,
    ParserError,
    ParserRetryableError,
)
from .logging_utils import build_model_log_extra
from .models import AppConfig, ParseResult, Task, TaskState
from .parser_client import ParserClient
from .review_result import extract_can_translate, split_review_columns
from .video_analysis_client import VideoAnalysisClient
from .volcengine_files_client import VolcengineFilesClient
from .volcengine_responses_client import VolcengineResponsesClient

TaskCallback = Callable[[Task], None]
T = TypeVar("T")


class TaskScheduler:
    """编排解析、解读、缓存与风控节奏。"""

    OUTPUT_FORMAT_PLAIN_TEXT = "plain_text"
    OUTPUT_FORMAT_JSON = "json"
    MAX_RETRIES_PER_SERVICE = 2
    BACKOFF_HARD_CAP_SECONDS = 30.0

    def __init__(
        self,
        parser: ParserClient,
        model_client: VideoAnalysisClient,
        cache: CacheStore,
        config: AppConfig,
        parser_breaker: CircuitBreaker,
        model_breaker: CircuitBreaker,
        logger: logging.Logger | None = None,
        volcengine_files_client: VolcengineFilesClient | None = None,
        volcengine_responses_client: VolcengineResponsesClient | None = None,
    ):
        self.parser = parser
        self.model_client = model_client
        self.cache = cache
        self.config = config
        self.parser_breaker = parser_breaker
        self.model_breaker = model_breaker
        self.logger = logger or logging.getLogger("video2prompt")
        self.volcengine_files_client = volcengine_files_client
        self.volcengine_responses_client = volcengine_responses_client

        self._circuit_reason: str | None = None
        self._default_user_prompt = ""
        self._output_format = self.OUTPUT_FORMAT_PLAIN_TEXT
        self._burst_penalty_factor = 1.0

    async def run(
        self,
        tasks: list[Task],
        user_prompt: str,
        output_format: str = OUTPUT_FORMAT_PLAIN_TEXT,
        on_update: TaskCallback | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        if cancel_event is None:
            cancel_event = asyncio.Event()

        self._default_user_prompt = user_prompt
        self._output_format = self._normalize_output_format(output_format)
        await self.run_batch(tasks, on_update=on_update, cancel_event=cancel_event)

    async def run_batch(
        self,
        tasks: list[Task],
        on_update: TaskCallback | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        if cancel_event is None:
            cancel_event = asyncio.Event()

        try:
            semaphore = asyncio.Semaphore(self.config.parser.concurrency)
            coros = [self.execute_task(task, semaphore, on_update=on_update, cancel_event=cancel_event) for task in tasks]
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

        try:
            if cancel_event.is_set():
                task.state = TaskState.CANCELLED
                return self._emit(task, on_update)

            await self._prepare_task_for_model(task, parser_semaphore, on_update, cancel_event)
            if task.cache_hit:
                await self._completion_delay(cancel_event=cancel_event)
                return

            await self._model_with_retry(task, on_update, cancel_event)

            task.state = TaskState.COMPLETED
            self._emit(task, on_update)
        except asyncio.CancelledError:
            task.state = TaskState.CANCELLED
            task.error_message = "任务已取消"
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
            await self._completion_delay(cancel_event=cancel_event)

    async def _prepare_task_for_model(
        self,
        task: Task,
        parser_semaphore: asyncio.Semaphore,
        on_update: TaskCallback | None,
        cancel_event: asyncio.Event,
    ) -> None:
        self._check_circuit()
        await self._handle_cache(task, on_update)
        if task.cache_hit:
            return

        await self._parse_with_retry(task, parser_semaphore, on_update, cancel_event)
        task.model_api_mode = await self._resolve_model_api_mode(task, cancel_event)

    async def _handle_cache(self, task: Task, on_update: TaskCallback | None) -> None:
        link_hash = self.cache.hash_link(task.original_link)
        prompt_hash = self._build_prompt_hash_for_cache()
        cached = await self.cache.get_cached_result(link_hash=link_hash, prompt_hash=prompt_hash)
        if cached is None:
            return
        task.cache_hit = True
        task.aweme_id = cached.aweme_id
        task.video_url = cached.video_url
        if self._output_format == self.OUTPUT_FORMAT_JSON:
            cached_can_translate, cached_summary = split_review_columns(cached.model_output)
            task.can_translate = cached.can_translate or cached_can_translate or extract_can_translate(cached.model_output)
            task.model_output = cached_summary or cached.model_output
        else:
            task.can_translate = cached.can_translate or ""
            task.model_output = cached.model_output
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
        max_attempts = min(len(backoff_seq) + 1, self.MAX_RETRIES_PER_SERVICE + 1)
        for attempt in range(1, max_attempts + 1):
            if cancel_event.is_set():
                task.state = TaskState.CANCELLED
                self._emit(task, on_update)
                raise asyncio.CancelledError("任务已取消")

            self._check_circuit()

            task.parse_retries = attempt - 1
            try:
                result = await self._parse_with_slot_cooldown(
                    task=task,
                    parser_semaphore=parser_semaphore,
                    on_update=on_update,
                    cancel_event=cancel_event,
                )
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
                await self._backoff_wait("parser", attempt, on_update=on_update, task=task, cancel_event=cancel_event)
            except ParserError as exc:
                # 对 4xx 这类链接/输入问题不计入熔断，避免误判为服务整体不可用。
                if self._is_parser_client_side_error(exc):
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
        backoff_seq = self.config.retry.model_backoff_seconds
        max_attempts = min(len(backoff_seq) + 1, self.MAX_RETRIES_PER_SERVICE + 1)
        api_mode = task.model_api_mode or "video_url"

        for attempt in range(1, max_attempts + 1):
            if cancel_event.is_set():
                task.state = TaskState.CANCELLED
                self._emit(task, on_update)
                raise asyncio.CancelledError("任务已取消")

            self._check_circuit()
            task.state = TaskState.INTERPRETING
            task.model_retries = attempt - 1
            self._emit(task, on_update)

            try:
                output, fps_used = await self._invoke_model(task, api_mode, cancel_event)
                self.model_breaker.record_success()
                self._burst_penalty_factor = max(1.0, self._burst_penalty_factor * 0.8)

                task.can_translate, task.model_output = self._parse_output_by_format(output)
                task.fps_used = fps_used
                self._inject_model_observation(task, api_mode)

                await self._save_task_cache(task)
                self.logger.info("模型解读成功 pid=%s", task.pid, extra=build_model_log_extra(task))
                return
            except ModelRetryableError as exc:
                message = str(exc)
                is_burst = self._is_burst_limit_error(message)
                is_fetch_error = (not is_burst) and self.model_client.is_video_fetch_error_message(message)
                if is_burst:
                    self._burst_penalty_factor = min(8.0, self._burst_penalty_factor * 1.8)
                    self.logger.warning(
                        "模型突发限流（RequestBurstTooFast），进入慢启动退避：factor=%.2f", self._burst_penalty_factor
                    )
                elif is_fetch_error:
                    self.logger.warning("模型可重试错误（视频直链访问失败，不计入熔断）: %s", exc)
                else:
                    self.model_breaker.record_failure()
                    self.logger.warning("模型可重试错误: %s", exc)

                if is_fetch_error and api_mode == "video_url":
                    switched = await self._try_fallback_video_url_to_file_id(
                        task,
                        message=message,
                        cancel_event=cancel_event,
                    )
                    if switched:
                        api_mode = "file_id"
                        continue
                    self.logger.info("检测到视频资源拉取失败，尝试重新解析直链")
                    await self._reparse_video_url(task, cancel_event=cancel_event)

                if (not is_burst) and self.model_breaker.is_tripped():
                    self._trip_circuit("模型服务熔断")
                if attempt >= max_attempts:
                    raise ModelError(f"模型重试耗尽: {exc}") from exc

                extra_delay = 0.0
                if is_burst:
                    base = self._base_backoff_delay("model", attempt)
                    extra_delay = max(0.0, base * (self._burst_penalty_factor - 1.0))
                await self._backoff_wait(
                    "model",
                    attempt,
                    on_update=on_update,
                    task=task,
                    extra_delay_seconds=extra_delay,
                    cancel_event=cancel_event,
                )
            except ModelError as exc:
                message = str(exc)
                is_fetch_error = self.model_client.is_video_fetch_error_message(message)
                if is_fetch_error:
                    self.logger.error("模型不可重试错误（视频直链访问失败，不计入熔断）: %s", exc)
                else:
                    self.model_breaker.record_failure()
                    self.logger.error("模型不可重试错误: %s", exc)

                if is_fetch_error and api_mode == "video_url":
                    switched = await self._try_fallback_video_url_to_file_id(
                        task,
                        message=message,
                        cancel_event=cancel_event,
                    )
                    if switched:
                        api_mode = "file_id"
                        continue
                    try:
                        await self._reparse_video_url(task, cancel_event=cancel_event)
                    except Exception as reparse_exc:  # noqa: BLE001
                        raise ModelError(f"模型失败，且重解析失败: {reparse_exc}") from exc
                    if attempt >= max_attempts:
                        raise ModelError(f"模型重试耗尽: {exc}") from exc
                    await self._backoff_wait("model", attempt, on_update=on_update, task=task, cancel_event=cancel_event)
                    continue
                if self.model_breaker.is_tripped():
                    self._trip_circuit("模型服务熔断")
                raise

    async def _invoke_model(self, task: Task, api_mode: str, cancel_event: asyncio.Event) -> tuple[str, float]:
        if api_mode == "file_id":
            return await self._invoke_responses_with_file(task, cancel_event=cancel_event)

        output, fps_used = await self._await_with_cancel(
            self.model_client.interpret_video(
                video_uri=task.video_url,
                user_prompt=self._default_user_prompt,
                fps=self.config.volcengine.video_fps,
                fps_fallback=None,
            ),
            cancel_event=cancel_event,
        )
        return output, fps_used

    async def _invoke_responses_with_file(self, task: Task, cancel_event: asyncio.Event) -> tuple[str, float]:
        if self.volcengine_files_client is None or self.volcengine_responses_client is None:
            raise ModelError("file_id 模式缺少 Files/Responses 客户端")

        temp_path = ""
        file_id = ""
        try:
            temp_path = await self._await_with_cancel(
                self.volcengine_files_client.download_video_to_temp(
                    task.video_url,
                    max_mb=self.config.volcengine.files_video_size_limit_mb,
                ),
                cancel_event=cancel_event,
            )
            file_id = await self._await_with_cancel(
                self.volcengine_files_client.upload_file(
                    temp_path,
                    fps=self.config.volcengine.video_fps,
                    expire_days=self.config.volcengine.files_expire_days,
                ),
                cancel_event=cancel_event,
            )
            await self._await_with_cancel(
                self.volcengine_files_client.poll_file_ready(
                    file_id=file_id,
                    timeout_seconds=self.config.volcengine.files_poll_timeout_seconds,
                ),
                cancel_event=cancel_event,
            )
            output = await self._await_with_cancel(
                self.volcengine_responses_client.create_response_with_file_id(
                    file_id=file_id,
                    prompt=self._default_user_prompt,
                ),
                cancel_event=cancel_event,
            )
            return output, self.config.volcengine.video_fps
        finally:
            if file_id:
                await self.volcengine_files_client.delete_file(file_id)
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    async def _resolve_model_api_mode(self, task: Task, cancel_event: asyncio.Event) -> str:
        input_mode = (self.config.volcengine.input_mode or "auto").strip().lower()
        video_url_limit = self.config.volcengine.video_url_size_limit_mb
        files_limit = self.config.volcengine.files_video_size_limit_mb
        size_mb = await self._probe_video_size_mb(task.video_url, cancel_event=cancel_event)

        if input_mode == "video_url":
            if size_mb is not None and size_mb > video_url_limit:
                raise ModelError(
                    f"视频文件过大（{size_mb:.1f} MiB > video_url 上限 {video_url_limit} MiB），请切换 input_mode=file_id/auto"
                )
            return "video_url"

        if input_mode == "file_id":
            if size_mb is not None and size_mb > files_limit:
                raise ModelError(
                    f"视频文件过大（{size_mb:.1f} MiB > Files 上限 {files_limit} MiB），已超过平台限制"
                )
            return "file_id"

        if size_mb is None:
            return "video_url"
        if size_mb <= video_url_limit:
            return "video_url"
        if size_mb <= files_limit:
            return "file_id"
        raise ModelError(f"视频文件过大（{size_mb:.1f} MiB > Files 上限 {files_limit} MiB），已超过平台限制")

    async def _probe_video_size_mb(self, url: str, cancel_event: asyncio.Event | None = None) -> float | None:
        if not url:
            return None

        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                if cancel_event is not None:
                    resp = await self._await_with_cancel(client.head(url), cancel_event=cancel_event)
                else:
                    resp = await client.head(url)
                size = self._size_from_headers(resp.headers)
                if size is not None:
                    return size

                # 部分源站不支持 HEAD，退化到 Range 探测。
                if cancel_event is not None:
                    resp = await self._await_with_cancel(
                        client.get(url, headers={"Range": "bytes=0-0"}),
                        cancel_event=cancel_event,
                    )
                else:
                    resp = await client.get(url, headers={"Range": "bytes=0-0"})
                size = self._size_from_headers(resp.headers)
                return size
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("视频大小探测失败（将回退 video_url 路径）: %s", exc)
            return None

    @staticmethod
    def _size_from_headers(headers: httpx.Headers) -> float | None:
        content_length = headers.get("content-length")
        if content_length:
            try:
                return int(content_length) / (1024 * 1024)
            except ValueError:
                pass

        content_range = headers.get("content-range", "")
        # 形如 bytes 0-0/12345
        if "/" in content_range:
            total = content_range.rsplit("/", 1)[-1].strip()
            if total.isdigit():
                return int(total) / (1024 * 1024)
        return None

    def _inject_model_observation(self, task: Task, api_mode: str) -> None:
        source: Any = self.model_client
        if api_mode == "file_id":
            source = self.volcengine_responses_client

        consume = getattr(source, "consume_last_observation", None)
        if not callable(consume):
            task.model_prompt_tokens = 0
            task.model_completion_tokens = 0
            task.model_reasoning_tokens = 0
            task.model_cached_tokens = 0
            task.model_request_id = ""
            task.model_api_mode = api_mode
            return

        payload = consume()
        task.model_prompt_tokens = int(payload.get("prompt_tokens", 0) or 0)
        task.model_completion_tokens = int(payload.get("completion_tokens", 0) or 0)
        task.model_reasoning_tokens = int(payload.get("reasoning_tokens", 0) or 0)
        task.model_cached_tokens = int(payload.get("cached_tokens", 0) or 0)
        task.model_request_id = str(payload.get("request_id", "") or "")
        task.model_api_mode = str(payload.get("api_mode", api_mode) or api_mode)

    async def _save_task_cache(self, task: Task) -> None:
        link_hash = self.cache.hash_link(task.original_link)
        prompt_hash = self._build_prompt_hash_for_cache()
        await self.cache.save_result(
            link_hash=link_hash,
            prompt_hash=prompt_hash,
            aweme_id=task.aweme_id,
            video_url=task.video_url,
            model_output=task.model_output,
            can_translate=task.can_translate,
            fps_used=task.fps_used,
        )

    async def _reparse_video_url(self, task: Task, cancel_event: asyncio.Event) -> None:
        result = await self._await_with_cancel(self.parser.parse_video(task.original_link), cancel_event=cancel_event)
        task.aweme_id = result.aweme_id
        task.video_url = result.video_url

    async def _try_fallback_video_url_to_file_id(
        self,
        task: Task,
        message: str,
        cancel_event: asyncio.Event,
    ) -> bool:
        input_mode = (self.config.volcengine.input_mode or "auto").strip().lower()
        if input_mode != "auto":
            return False
        if self.volcengine_files_client is None or self.volcengine_responses_client is None:
            return False

        size_mb = await self._probe_video_size_mb(task.video_url, cancel_event=cancel_event)
        files_limit = float(self.config.volcengine.files_video_size_limit_mb)
        if size_mb is not None and size_mb > files_limit:
            self.logger.warning(
                "视频直链访问失败且无法回退 file_id：文件过大 %.1f MiB > %.1f MiB, err=%s",
                size_mb,
                files_limit,
                message,
            )
            return False

        task.model_api_mode = "file_id"
        self.logger.info("检测到 video_url 拉取失败，自动回退 file_id 重试")
        return True

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

    async def _backoff_wait(
        self,
        service: str,
        attempt: int,
        on_update: TaskCallback | None = None,
        task: Task | None = None,
        extra_delay_seconds: float = 0.0,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        cap: int
        base_delay = self._base_backoff_delay(service, attempt)
        if service == "parser":
            cap = int(self.config.retry.parser_backoff_cap_seconds)
        else:
            cap = int(self.config.retry.model_backoff_cap_seconds)

        hard_cap = min(float(cap), self.BACKOFF_HARD_CAP_SECONDS)
        delay = min(base_delay + max(0.0, float(extra_delay_seconds)), hard_cap)
        delay_with_jitter = min(delay + random.uniform(0.0, 1.0), hard_cap)

        if task is not None:
            task.state = TaskState.INTERVAL
            task.error_message = f"{service} 退避 {delay_with_jitter:.1f}s"
            self._emit(task, on_update)

        if cancel_event is None:
            await asyncio.sleep(delay_with_jitter)
            return
        await self._sleep_with_cancel(delay_with_jitter, cancel_event=cancel_event)

    def _base_backoff_delay(self, service: str, attempt: int) -> float:
        if service == "parser":
            seq = self.config.retry.parser_backoff_seconds
            cap = self.config.retry.parser_backoff_cap_seconds
        else:
            seq = self.config.retry.model_backoff_seconds
            cap = self.config.retry.model_backoff_cap_seconds

        idx = max(0, min(attempt - 1, len(seq) - 1))
        return float(min(int(seq[idx]), int(cap), int(self.BACKOFF_HARD_CAP_SECONDS)))

    def _check_circuit(self) -> None:
        if self._circuit_reason:
            raise CircuitBreakerOpenError(self._circuit_reason)

    def _trip_circuit(self, reason: str) -> None:
        self._circuit_reason = reason
        raise CircuitBreakerOpenError(reason)

    @staticmethod
    def _is_parser_client_side_error(exc: ParserError) -> bool:
        return isinstance(exc, ParserClientSideError)

    @staticmethod
    def _is_burst_limit_error(message: str) -> bool:
        return "requestbursttoofast" in (message or "").lower()

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

    @staticmethod
    def _emit(task: Task, on_update: TaskCallback | None) -> None:
        if on_update is not None:
            on_update(task)

    @staticmethod
    def _chunk_tasks(tasks: list[Task], size: int) -> list[list[Task]]:
        if size <= 0:
            return [tasks]
        return [tasks[i : i + size] for i in range(0, len(tasks), size)]

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
        if delay > 0:
            await asyncio.sleep(delay)

    def reset_circuit(self) -> None:
        self._circuit_reason = None
        self._burst_penalty_factor = 1.0
        self.parser_breaker.reset()
        self.model_breaker.reset()

    @classmethod
    def _normalize_output_format(cls, output_format: str) -> str:
        normalized = (output_format or "").strip().lower()
        if normalized == cls.OUTPUT_FORMAT_JSON:
            return cls.OUTPUT_FORMAT_JSON
        return cls.OUTPUT_FORMAT_PLAIN_TEXT

    def _build_prompt_hash_for_cache(self) -> str:
        if self.config.cache.include_prompt_hash_in_key:
            cache_key_source = f"{self._default_user_prompt}\n#输出格式={self._output_format}"
            return self.cache.hash_prompt(cache_key_source)
        return self.cache.hash_prompt(f"#输出格式={self._output_format}")

    def _parse_output_by_format(self, output: str) -> tuple[str, str]:
        text = str(output or "").strip()
        if self._output_format == self.OUTPUT_FORMAT_JSON:
            return split_review_columns(text)
        return "", text
