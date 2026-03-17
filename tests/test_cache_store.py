from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from video2prompt.cache_store import CacheStore


@pytest.mark.asyncio
async def test_cache_store_migrates_gemini_output_to_model_output(tmp_path: Path) -> None:
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
