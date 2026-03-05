from __future__ import annotations

import asyncio
import time

from video2prompt.circuit_breaker import CircuitBreaker
from video2prompt.errors import ParserRetryableError
from video2prompt.models import AppConfig, ParseResult, ParserConfig, RetryConfig, Task, TaskConfig
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
        can_translate: str,
        fps_used: float,
    ) -> None:
        del link_hash, prompt_hash, aweme_id, video_url, gemini_output, can_translate, fps_used
        return None


class _StubModel:
    async def interpret_video(
        self,
        video_uri: str,
        user_prompt: str,
        fps: float,
        fps_fallback: float | None = None,
    ) -> tuple[str, float]:
        del video_uri, user_prompt, fps_fallback
        return "ok", fps

    def is_video_fetch_error_message(self, message: str) -> bool:
        del message
        return False

    def consume_last_observation(self) -> dict[str, int | str]:
        return {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "reasoning_tokens": 0,
            "cached_tokens": 0,
            "request_id": "req-1",
            "api_mode": "chat",
        }


class _TimedParser:
    def __init__(self) -> None:
        self.starts: list[float] = []

    async def parse_video(self, url: str) -> ParseResult:
        self.starts.append(time.monotonic())
        return ParseResult(aweme_id=f"aweme-{url}", video_url=f"https://example.com/{url}.mp4", raw_data={})


class _FailOnceParser:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []
        self._failed = False

    async def parse_video(self, url: str) -> ParseResult:
        self.calls.append((url, time.monotonic()))
        if url == "a" and not self._failed:
            self._failed = True
            raise ParserRetryableError("temporary parser error")
        return ParseResult(aweme_id=f"aweme-{url}", video_url=f"https://example.com/{url}.mp4", raw_data={})


class _AlwaysRetryableParser:
    def __init__(self) -> None:
        self.calls = 0

    async def parse_video(self, url: str) -> ParseResult:
        del url
        self.calls += 1
        raise ParserRetryableError("always fail")


def _make_scheduler(parser, config: AppConfig) -> TaskScheduler:  # noqa: ANN001
    parser_breaker = CircuitBreaker(consecutive_threshold=20, rate_threshold=1.0, window_seconds=60)
    gemini_breaker = CircuitBreaker(consecutive_threshold=20, rate_threshold=1.0, window_seconds=60)
    return TaskScheduler(
        parser=parser,
        model_client=_StubModel(),
        cache=_StubCache(),
        config=config,
        parser_breaker=parser_breaker,
        gemini_breaker=gemini_breaker,
    )


def _base_config(
    *,
    concurrency: int,
    cooldown_seconds: float,
    parser_backoff: list[int],
) -> AppConfig:
    return AppConfig(
        parser=ParserConfig(
            concurrency=concurrency,
            pre_delay_min_seconds=cooldown_seconds,
            pre_delay_max_seconds=cooldown_seconds,
            timeout_seconds=30,
        ),
        retry=RetryConfig(
            parser_backoff_seconds=parser_backoff,
            gemini_backoff_seconds=[1],
            parser_backoff_cap_seconds=30,
            gemini_backoff_cap_seconds=30,
            pause_global_queue_during_backoff=True,
        ),
        task=TaskConfig(completion_delay_min_seconds=0.0, completion_delay_max_seconds=0.0),
    )


def test_parse_slot_cooldown_holds_parser_slot() -> None:
    parser = _TimedParser()
    scheduler = _make_scheduler(
        parser,
        _base_config(concurrency=1, cooldown_seconds=0.05, parser_backoff=[1]),
    )
    tasks = [Task(pid="1", original_link="a"), Task(pid="2", original_link="b")]

    async def _run() -> None:
        await scheduler.run(tasks=tasks, user_prompt="prompt", cancel_event=asyncio.Event())

    asyncio.run(_run())

    assert len(parser.starts) == 2
    assert parser.starts[1] - parser.starts[0] >= 0.045


def test_parser_backoff_no_longer_pauses_other_tasks_globally() -> None:
    parser = _FailOnceParser()
    scheduler = _make_scheduler(
        parser,
        _base_config(concurrency=1, cooldown_seconds=0.0, parser_backoff=[2]),
    )
    task_a = Task(pid="1", original_link="a")
    task_b = Task(pid="2", original_link="b")

    async def _run() -> None:
        await scheduler.run(tasks=[task_a, task_b], user_prompt="prompt", cancel_event=asyncio.Event())

    asyncio.run(_run())

    assert task_a.state.value == "完成"
    assert task_b.state.value == "完成"
    assert parser.calls[0][0] == "a"
    first_a = parser.calls[0][1]
    first_b = next(ts for url, ts in parser.calls if url == "b")
    assert first_b - first_a < 0.5


def test_parser_retry_is_limited_to_two_retries() -> None:
    parser = _AlwaysRetryableParser()
    scheduler = _make_scheduler(
        parser,
        _base_config(concurrency=1, cooldown_seconds=0.0, parser_backoff=[1, 1, 1, 1]),
    )
    task = Task(pid="1", original_link="a")

    async def _fake_backoff(  # noqa: ANN202
        service: str,
        attempt: int,
        on_update=None,  # noqa: ANN001
        task=None,  # noqa: ANN001
        extra_delay_seconds: float = 0.0,
    ):
        del service, attempt, on_update, task, extra_delay_seconds
        return None

    scheduler._backoff_wait = _fake_backoff  # type: ignore[method-assign]

    async def _run() -> None:
        await scheduler.run(tasks=[task], user_prompt="prompt", cancel_event=asyncio.Event())

    asyncio.run(_run())

    assert task.state.value == "失败"
    assert task.parse_retries == 2
    assert parser.calls == 3


def test_backoff_sleep_hard_cap_30_seconds(monkeypatch) -> None:  # noqa: ANN001
    scheduler = _make_scheduler(
        _TimedParser(),
        _base_config(concurrency=1, cooldown_seconds=0.0, parser_backoff=[10]),
    )
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("video2prompt.task_scheduler.asyncio.sleep", _fake_sleep)
    monkeypatch.setattr("video2prompt.task_scheduler.random.uniform", lambda _a, _b: 1.0)

    async def _run() -> None:
        await scheduler._backoff_wait("parser", attempt=1, extra_delay_seconds=1000)

    asyncio.run(_run())

    assert sleeps == [30.0]
