from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
import pytest

from video2prompt.cache_store import CacheStore


@pytest.mark.asyncio
async def test_cache_store_migrates_gemini_output_to_model_output(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "cache.db"

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE cache (
                link_hash TEXT NOT NULL,
                prompt_hash TEXT NOT NULL,
                aweme_id TEXT NOT NULL,
                video_url TEXT NOT NULL,
                gemini_output TEXT NOT NULL DEFAULT '',
                can_translate TEXT NOT NULL DEFAULT '',
                fps_used REAL NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (link_hash, prompt_hash)
            )
            """
        )
        await db.execute(
            """
            INSERT INTO cache (link_hash, prompt_hash, aweme_id, video_url, gemini_output, can_translate, fps_used)
            VALUES ('link', 'prompt', 'aweme-1', 'https://example.com/video.mp4', '结果', '能', 1.5)
            """
        )
        await db.commit()

    store = CacheStore(db_path=str(db_path))
    await store.init_db()

    cached = await store.get_cached_result("link", "prompt")

    assert cached is not None
    assert cached.model_output == "结果"
    assert cached.can_translate == "能"
    assert cached.fps_used == 1.5


@pytest.mark.asyncio
async def test_cache_store_save_and_load_setting(tmp_path: Path) -> None:
    store = CacheStore(db_path=str(tmp_path / "cache.db"))
    await store.init_db()

    await store.save_setting("prompt.video_prompt", "value-a")

    assert await store.load_setting("prompt.video_prompt") == "value-a"


@pytest.mark.asyncio
async def test_cache_store_keeps_legacy_system_prompt_behavior(tmp_path: Path) -> None:
    store = CacheStore(db_path=str(tmp_path / "cache.db"))
    await store.init_db()

    await store.save_system_prompt("legacy")

    assert await store.load_system_prompt() == "legacy"


@pytest.mark.asyncio
async def test_cache_store_serializes_concurrent_connections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = CacheStore(db_path=str(tmp_path / "cache.db"))

    entered = 0
    max_entered = 0
    enter_gate = asyncio.Event()

    class _FakeCursor:
        async def fetchone(self):
            return None

        async def close(self) -> None:
            return None

    class _FakeConnection:
        async def __aenter__(self):
            nonlocal entered, max_entered
            entered += 1
            max_entered = max(max_entered, entered)
            await enter_gate.wait()
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            nonlocal entered
            entered -= 1

        async def execute(self, *_args, **_kwargs):
            return _FakeCursor()

    monkeypatch.setattr(aiosqlite, "connect", lambda _path: _FakeConnection())

    first = asyncio.create_task(store.get_cached_result("a", "b"))
    second = asyncio.create_task(store.get_cached_result("c", "d"))
    await asyncio.sleep(0)
    enter_gate.set()
    await asyncio.gather(first, second)

    assert max_entered == 1
