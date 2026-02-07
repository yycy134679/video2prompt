"""SQLite 缓存实现。"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import aiosqlite

from .models import CachedResult


class CacheStore:
    """缓存与 prompt 持久化。"""

    def __init__(self, db_path: str = "data/cache.db"):
        self.db_path = db_path

    async def init_db(self) -> None:
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    link_hash TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    aweme_id TEXT NOT NULL,
                    video_url TEXT NOT NULL,
                    gemini_output TEXT NOT NULL DEFAULT '',
                    fps_used REAL NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (link_hash, prompt_hash)
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS system_prompt (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    content TEXT NOT NULL DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.commit()

    @staticmethod
    def hash_link(link: str) -> str:
        return hashlib.sha256(link.strip().encode("utf-8")).hexdigest()

    @staticmethod
    def hash_prompt(prompt: str) -> str:
        return hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()

    async def get_cached_result(self, link_hash: str, prompt_hash: str) -> CachedResult | None:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT link_hash, prompt_hash, aweme_id, video_url, gemini_output, fps_used, created_at
                FROM cache WHERE link_hash = ? AND prompt_hash = ?
                """,
                (link_hash, prompt_hash),
            )
            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None

        return CachedResult(
            link_hash=row[0],
            prompt_hash=row[1],
            aweme_id=row[2],
            video_url=row[3],
            gemini_output=row[4],
            fps_used=float(row[5]),
            created_at=datetime.fromisoformat(str(row[6])),
        )

    async def save_result(
        self,
        link_hash: str,
        prompt_hash: str,
        aweme_id: str,
        video_url: str,
        gemini_output: str,
        fps_used: float,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO cache (link_hash, prompt_hash, aweme_id, video_url, gemini_output, fps_used)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(link_hash, prompt_hash)
                DO UPDATE SET
                    aweme_id = excluded.aweme_id,
                    video_url = excluded.video_url,
                    gemini_output = excluded.gemini_output,
                    fps_used = excluded.fps_used,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (link_hash, prompt_hash, aweme_id, video_url, gemini_output, fps_used),
            )
            await db.commit()

    async def save_system_prompt(self, prompt: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO system_prompt (id, content)
                VALUES (1, ?)
                ON CONFLICT(id)
                DO UPDATE SET content = excluded.content, updated_at = CURRENT_TIMESTAMP
                """,
                (prompt,),
            )
            await db.commit()

    async def load_system_prompt(self) -> str | None:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT content FROM system_prompt WHERE id = 1")
            row = await cursor.fetchone()
            await cursor.close()
        if row is None:
            return None
        return str(row[0])
