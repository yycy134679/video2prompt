from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from video2prompt.circuit_breaker import CircuitBreaker
from video2prompt.errors import GeminiRetryableError
from video2prompt.models import (
    AppConfig,
    ParseResult,
    ParserConfig,
    RetryConfig,
    Task,
    VolcengineConfig,
)
from video2prompt.task_scheduler import TaskScheduler


class _StubCache:
    def hash_link(self, link: str) -> str:
        return f"h:{link}"

    def hash_prompt(self, prompt: str) -> str:
        return f"p:{prompt}"

    async def get_cached_result(self, link_hash: str, prompt_hash: str):  # noqa: ANN001
        del link_hash, prompt_hash
        return None

    async def save_result(
        self,
        link_hash: str,
        prompt_hash: str,
        aweme_id: str,
        video_url: str,
        gemini_output: str,
        fps_used: float,
    ) -> None:
        del link_hash, prompt_hash, aweme_id, video_url, gemini_output, fps_used
        return None


class _StubParser:
    async def parse_video(self, _: str) -> ParseResult:
        return ParseResult(aweme_id="aweme-1", video_url="https://example.com/video.mp4", raw_data={})


@dataclass
class _RetryModel:
    errors: list[Exception]
    output: str = "ok"
    calls: int = 0

    async def interpret_video(
        self,
        video_uri: str,
        user_prompt: str,
        fps: float,
        fps_fallback: float | None = None,
    ) -> tuple[str, float]:
        del video_uri, user_prompt, fps_fallback
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.output, fps

    def is_video_fetch_error_message(self, message: str) -> bool:
        del message
        return False

    def consume_last_observation(self) -> dict[str, int | str]:
        return {
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "reasoning_tokens": 0,
            "cached_tokens": 0,
            "request_id": "req-1",
            "api_mode": "chat",
        }


class _StubFilesClient:
    async def download_video_to_temp(self, url: str, max_mb: int) -> str:
        del url, max_mb
        return "/tmp/fake.mp4"

    async def upload_file(self, path: str, fps: float, model: str, expire_days: int = 7) -> str:
        del path, fps, model, expire_days
        return "file-123"

    async def poll_file_ready(self, file_id: str, timeout_seconds: int) -> None:
        del file_id, timeout_seconds
        return None

    async def delete_file(self, file_id: str) -> None:
        del file_id
        return None


class _StubResponsesClient:
    async def create_response_with_file_id(self, file_id: str, prompt: str) -> str:
        del file_id, prompt
        return "responses-ok"

    def consume_last_observation(self) -> dict[str, int | str]:
        return {
            "prompt_tokens": 3,
            "completion_tokens": 4,
            "reasoning_tokens": 1,
            "cached_tokens": 0,
            "request_id": "req-resp",
            "api_mode": "responses",
        }


def _make_scheduler(
    model_client,
    config: AppConfig,
    *,
    files_client=None,
    responses_client=None,
) -> TaskScheduler:
    parser_breaker = CircuitBreaker(consecutive_threshold=5, rate_threshold=1.0, window_seconds=60)
    gemini_breaker = CircuitBreaker(consecutive_threshold=5, rate_threshold=1.0, window_seconds=60)
    return TaskScheduler(
        parser=_StubParser(),
        model_client=model_client,
        cache=_StubCache(),
        config=config,
        parser_breaker=parser_breaker,
        gemini_breaker=gemini_breaker,
        volcengine_files_client=files_client,
        volcengine_responses_client=responses_client,
    )


def _make_volc_config(**kwargs) -> AppConfig:  # noqa: ANN003
    volc = VolcengineConfig(
        endpoint_id="ep-test",
        target_model="seed-2.0-lite",
        input_mode="chat_url",
    )
    for key, value in kwargs.items():
        setattr(volc, key, value)
    return AppConfig(
        provider="volcengine",
        volcengine=volc,
        parser=ParserConfig(concurrency=1, pre_delay_min_seconds=0.0, pre_delay_max_seconds=0.0, timeout_seconds=30),
        retry=RetryConfig(
            parser_backoff_seconds=[1],
            gemini_backoff_seconds=[1],
            parser_backoff_cap_seconds=5,
            gemini_backoff_cap_seconds=5,
            pause_global_queue_during_backoff=False,
        ),
    )


def test_request_burst_too_fast_uses_penalty_backoff() -> None:
    model = _RetryModel(errors=[GeminiRetryableError("火山状态码 429: code=RequestBurstTooFast")])
    scheduler = _make_scheduler(model, _make_volc_config())
    task = Task(pid="1", original_link="https://example.com/share/1")
    calls: list[float] = []

    async def _fake_backoff(
        service: str,
        attempt: int,
        on_update: Callable | None = None,
        task: Task | None = None,
        extra_delay_seconds: float = 0.0,
    ) -> None:
        del service, attempt, on_update, task
        calls.append(extra_delay_seconds)
        return None

    scheduler._backoff_wait = _fake_backoff  # type: ignore[method-assign]

    async def _run() -> None:
        scheduler._probe_video_size_mb = _async_return(10.0)  # type: ignore[method-assign]
        await scheduler.execute_task(task, asyncio.Semaphore(1), cancel_event=asyncio.Event())

    asyncio.run(_run())
    assert task.state.value == "完成"
    assert calls and calls[0] > 0
    assert scheduler.gemini_breaker.is_tripped() is False


def test_server_overloaded_uses_normal_backoff() -> None:
    model = _RetryModel(errors=[GeminiRetryableError("火山状态码 429: code=ServerOverloaded")])
    scheduler = _make_scheduler(model, _make_volc_config())
    task = Task(pid="2", original_link="https://example.com/share/2")
    calls: list[float] = []

    async def _fake_backoff(
        service: str,
        attempt: int,
        on_update: Callable | None = None,
        task: Task | None = None,
        extra_delay_seconds: float = 0.0,
    ) -> None:
        del service, attempt, on_update, task
        calls.append(extra_delay_seconds)
        return None

    scheduler._backoff_wait = _fake_backoff  # type: ignore[method-assign]

    async def _run() -> None:
        scheduler._probe_video_size_mb = _async_return(10.0)  # type: ignore[method-assign]
        await scheduler.execute_task(task, asyncio.Semaphore(1), cancel_event=asyncio.Event())

    asyncio.run(_run())
    assert task.state.value == "完成"
    assert calls == [0.0]


def test_large_video_switches_to_responses_file() -> None:
    model = _RetryModel(errors=[], output="chat-should-not-run")
    files_client = _StubFilesClient()
    responses_client = _StubResponsesClient()
    scheduler = _make_scheduler(
        model,
        _make_volc_config(input_mode="auto", chat_video_size_limit_mb=50, files_video_size_limit_mb=512),
        files_client=files_client,
        responses_client=responses_client,
    )
    task = Task(pid="3", original_link="https://example.com/share/3")

    async def _run() -> None:
        scheduler._probe_video_size_mb = _async_return(120.0)  # type: ignore[method-assign]
        await scheduler.execute_task(task, asyncio.Semaphore(1), cancel_event=asyncio.Event())

    asyncio.run(_run())
    assert task.state.value == "完成"
    assert task.model_api_mode == "responses"
    assert task.gemini_output == "responses-ok"
    assert model.calls == 0


def _async_return(value):
    async def _inner(*args, **kwargs):  # noqa: ANN002, ANN003
        del args, kwargs
        return value

    return _inner
