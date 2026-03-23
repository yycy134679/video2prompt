from __future__ import annotations

import asyncio

import pytest

from video2prompt.duration_check_runner import DurationCheckRunner
from video2prompt.errors import ParserRetryableError
from video2prompt.models import AppConfig, ParseResult, ParserConfig, RetryConfig, Task, TaskConfig


class _ParserByLink:
    def __init__(self) -> None:
        self.calls = 0

    async def parse_video(self, url: str) -> ParseResult:
        self.calls += 1
        return ParseResult(aweme_id=f"aweme-{url}", video_url=f"https://example.com/{url}.mp4", raw_data={})


class _AlwaysRetryableParser:
    def __init__(self) -> None:
        self.calls = 0

    async def parse_video(self, url: str) -> ParseResult:
        del url
        self.calls += 1
        raise ParserRetryableError("temporary parser error")


def _make_config(*, parser_backoff: list[int]) -> AppConfig:
    return AppConfig(
        parser=ParserConfig(
            concurrency=3,
            pre_delay_min_seconds=0.0,
            pre_delay_max_seconds=0.0,
            timeout_seconds=30,
        ),
        retry=RetryConfig(
            parser_backoff_seconds=parser_backoff,
            model_backoff_seconds=[1],
            parser_backoff_cap_seconds=30,
            model_backoff_cap_seconds=30,
            pause_global_queue_during_backoff=True,
        ),
        task=TaskConfig(
            completion_delay_min_seconds=0.0,
            completion_delay_max_seconds=0.0,
        ),
    )


def test_duration_bucket_with_15_seconds_boundary() -> None:
    parser = _ParserByLink()
    runner = DurationCheckRunner(parser=parser, config=_make_config(parser_backoff=[1]))
    runner._ensure_ffprobe_available = lambda: None  # type: ignore[method-assign]
    duration_map = {
        "https://example.com/a.mp4": 14.2,
        "https://example.com/b.mp4": 15.0,
        "https://example.com/c.mp4": 15.1,
    }

    async def _fake_probe(video_url: str, cancel_event: asyncio.Event) -> float:
        del cancel_event
        return duration_map[video_url]

    runner._probe_duration_seconds = _fake_probe  # type: ignore[method-assign]
    tasks = [
        Task(pid="1", original_link="a"),
        Task(pid="2", original_link="b"),
        Task(pid="3", original_link="c"),
    ]

    async def _run() -> None:
        await runner.run(tasks=tasks, cancel_event=asyncio.Event())

    asyncio.run(_run())

    assert tasks[0].duration_check_bucket == "le_15"
    assert tasks[1].duration_check_bucket == "le_15"
    assert tasks[2].duration_check_bucket == "gt_15"
    assert tasks[0].state.value == "完成"
    assert tasks[1].state.value == "完成"
    assert tasks[2].state.value == "完成"


def test_ffprobe_failure_marks_task_failed() -> None:
    parser = _ParserByLink()
    runner = DurationCheckRunner(parser=parser, config=_make_config(parser_backoff=[1]))
    runner._ensure_ffprobe_available = lambda: None  # type: ignore[method-assign]

    async def _fake_probe(video_url: str, cancel_event: asyncio.Event) -> float:
        del video_url, cancel_event
        raise RuntimeError("ffprobe 执行失败: 403")

    runner._probe_duration_seconds = _fake_probe  # type: ignore[method-assign]
    task = Task(pid="1", original_link="x")

    async def _run() -> None:
        await runner.run(tasks=[task], cancel_event=asyncio.Event())

    asyncio.run(_run())

    assert task.state.value == "失败"
    assert task.duration_check_bucket == "failed"
    assert "ffprobe 执行失败" in task.error_message


def test_parse_retry_exhausted_marks_failed() -> None:
    parser = _AlwaysRetryableParser()
    runner = DurationCheckRunner(parser=parser, config=_make_config(parser_backoff=[1, 1, 1, 1]))
    runner._ensure_ffprobe_available = lambda: None  # type: ignore[method-assign]

    async def _noop_backoff(  # noqa: ANN202
        attempt: int,
        task=None,  # noqa: ANN001
        on_update=None,  # noqa: ANN001
        cancel_event=None,  # noqa: ANN001
    ):
        del attempt, task, on_update, cancel_event
        return None

    runner._backoff_wait = _noop_backoff  # type: ignore[method-assign]
    task = Task(pid="1", original_link="x")

    async def _run() -> None:
        await runner.run(tasks=[task], cancel_event=asyncio.Event())

    asyncio.run(_run())

    assert parser.calls == 3
    assert task.parse_retries == 2
    assert task.state.value == "失败"
    assert task.duration_check_bucket == "failed"
    assert "解析重试耗尽" in task.error_message


def test_run_fails_fast_when_ffprobe_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = _ParserByLink()
    runner = DurationCheckRunner(parser=parser, config=_make_config(parser_backoff=[1]))
    monkeypatch.setattr("video2prompt.duration_check_runner.shutil.which", lambda _: None)

    async def _run() -> None:
        await runner.run(tasks=[Task(pid="1", original_link="x")], cancel_event=asyncio.Event())

    with pytest.raises(RuntimeError, match="ffprobe"):
        asyncio.run(_run())


def test_resolve_ffprobe_command_prefers_explicit_path(tmp_path) -> None:
    parser = _ParserByLink()
    ffprobe_path = tmp_path / "ffprobe"
    ffprobe_path.write_text("", encoding="utf-8")
    runner = DurationCheckRunner(
        parser=parser,
        config=_make_config(parser_backoff=[1]),
        ffprobe_path=str(ffprobe_path),
    )

    assert runner.resolve_ffprobe_command() == str(ffprobe_path)
