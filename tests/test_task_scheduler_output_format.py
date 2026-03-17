from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

from video2prompt.circuit_breaker import CircuitBreaker
from video2prompt.models import AppConfig, ParseResult, ParserConfig, RetryConfig, Task, TaskConfig
from video2prompt.task_scheduler import TaskScheduler


class _MemoryCache:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], SimpleNamespace] = {}
        self.get_prompt_hashes: list[str] = []

    def hash_link(self, link: str) -> str:
        return f"link:{link}"

    def hash_prompt(self, prompt: str) -> str:
        return f"prompt:{prompt}"

    async def get_cached_result(self, link_hash: str, prompt_hash: str):  # noqa: ANN001
        self.get_prompt_hashes.append(prompt_hash)
        return self.rows.get((link_hash, prompt_hash))

    async def save_result(
        self,
        link_hash: str,
        prompt_hash: str,
        aweme_id: str,
        video_url: str,
        model_output: str,
        can_translate: str,
        fps_used: float,
    ) -> None:
        self.rows[(link_hash, prompt_hash)] = SimpleNamespace(
            aweme_id=aweme_id,
            video_url=video_url,
            model_output=model_output,
            can_translate=can_translate,
            fps_used=fps_used,
        )


class _StubParser:
    async def parse_video(self, _: str) -> ParseResult:
        return ParseResult(aweme_id="aweme-1", video_url="https://example.com/video.mp4", raw_data={})


@dataclass
class _QueueModel:
    outputs: list[str]
    calls: int = 0

    async def interpret_video(
        self,
        video_uri: str,
        user_prompt: str,
        fps: float,
        fps_fallback: float | None = None,
    ) -> tuple[str, float]:
        del video_uri, user_prompt, fps_fallback
        idx = min(self.calls, len(self.outputs) - 1)
        self.calls += 1
        return self.outputs[idx], fps

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


def _make_scheduler(model_client: _QueueModel, cache: _MemoryCache) -> TaskScheduler:
    parser_breaker = CircuitBreaker(consecutive_threshold=5, rate_threshold=1.0, window_seconds=60)
    model_breaker = CircuitBreaker(consecutive_threshold=5, rate_threshold=1.0, window_seconds=60)
    config = AppConfig(
        parser=ParserConfig(concurrency=1, pre_delay_min_seconds=0.0, pre_delay_max_seconds=0.0, timeout_seconds=30),
        retry=RetryConfig(
            parser_backoff_seconds=[1],
            model_backoff_seconds=[1],
            parser_backoff_cap_seconds=5,
            model_backoff_cap_seconds=5,
            pause_global_queue_during_backoff=False,
        ),
        task=TaskConfig(completion_delay_min_seconds=0.0, completion_delay_max_seconds=0.0),
    )
    return TaskScheduler(
        parser=_StubParser(),
        model_client=model_client,
        cache=cache,
        config=config,
        parser_breaker=parser_breaker,
        model_breaker=model_breaker,
    )


def test_json_output_keeps_current_parsing_behavior() -> None:
    raw = (
        '{"结论":{"能否翻译":"能"},'
        '"信息":{"儿童口播":"无","多人口播":"无","明确价格/促销信息":"有",'
        '"中文字符":{"字幕":"无","贴纸/花字":"无","其他":"无"}}}'
    )
    scheduler = _make_scheduler(_QueueModel(outputs=[raw]), _MemoryCache())
    task = Task(pid="1", original_link="https://example.com/share/1")

    async def _run() -> None:
        await scheduler.run(
            tasks=[task],
            user_prompt="测试提示词",
            output_format="json",
            cancel_event=asyncio.Event(),
        )

    asyncio.run(_run())

    assert task.state.value == "完成"
    assert task.can_translate == "不能"
    assert "3. 明确价格/促销信息：有" in task.model_output


def test_plain_text_mode_skips_structured_parse_even_on_cache_hit() -> None:
    raw = '{"结论":{"能否翻译":"能"},"信息":{"儿童口播":"无"}}'
    model = _QueueModel(outputs=[raw, "不会被使用"])
    cache = _MemoryCache()
    scheduler = _make_scheduler(model, cache)
    first = Task(pid="1", original_link="https://example.com/share/1")
    second = Task(pid="2", original_link="https://example.com/share/1")

    async def _run() -> None:
        await scheduler.run(
            tasks=[first],
            user_prompt="测试提示词",
            output_format="plain_text",
            cancel_event=asyncio.Event(),
        )
        await scheduler.run(
            tasks=[second],
            user_prompt="测试提示词",
            output_format="plain_text",
            cancel_event=asyncio.Event(),
        )

    asyncio.run(_run())

    assert model.calls == 1
    assert first.can_translate == ""
    assert first.model_output == raw
    assert second.cache_hit is True
    assert second.can_translate == ""
    assert second.model_output == raw


def test_cache_key_includes_output_format() -> None:
    model = _QueueModel(
        outputs=[
            "第一条纯文本结果",
            '{"结论":{"能否翻译":"能"},"信息":{"儿童口播":"无","多人口播":"无","明确价格/促销信息":"无","中文字符":{"字幕":"无","贴纸/花字":"无","其他":"无"}}}',
        ]
    )
    cache = _MemoryCache()
    scheduler = _make_scheduler(model, cache)
    plain_task = Task(pid="1", original_link="https://example.com/share/1")
    json_task = Task(pid="2", original_link="https://example.com/share/1")

    async def _run() -> None:
        await scheduler.run(
            tasks=[plain_task],
            user_prompt="相同提示词",
            output_format="plain_text",
            cancel_event=asyncio.Event(),
        )
        await scheduler.run(
            tasks=[json_task],
            user_prompt="相同提示词",
            output_format="json",
            cancel_event=asyncio.Event(),
        )

    asyncio.run(_run())

    assert model.calls == 2
    assert len(cache.get_prompt_hashes) >= 2
    assert cache.get_prompt_hashes[0] != cache.get_prompt_hashes[1]
