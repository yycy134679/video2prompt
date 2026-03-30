"""SQLite 缓存实现。"""

from __future__ import annotations

import asyncio
import hashlib
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import aiosqlite

from .models import CachedResult


class CacheStore:
    """缓存与 prompt 持久化。"""

    def __init__(self, db_path: str = "data/cache.db"):
        self.db_path = db_path
        self._connection_lock = threading.Lock()

    @asynccontextmanager
    async def _acquire_connection_lock(self):
        await asyncio.to_thread(self._connection_lock.acquire)
        try:
            yield
        finally:
            self._connection_lock.release()

    async def _connect(self):
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return aiosqlite.connect(self.db_path)

    async def init_db(self) -> None:
        async with self._acquire_connection_lock():
            async with await self._connect() as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cache (
                        link_hash TEXT NOT NULL,
                        prompt_hash TEXT NOT NULL,
                        aweme_id TEXT NOT NULL,
                        video_url TEXT NOT NULL,
                        model_output TEXT NOT NULL DEFAULT '',
                        can_translate TEXT NOT NULL DEFAULT '',
                        fps_used REAL NOT NULL DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (link_hash, prompt_hash)
                    )
                    """
                )
                cursor = await db.execute("PRAGMA table_info(cache)")
                columns = {str(row[1]) for row in await cursor.fetchall()}
                await cursor.close()
                if "model_output" not in columns:
                    await db.execute(
                        "ALTER TABLE cache ADD COLUMN model_output TEXT NOT NULL DEFAULT ''"
                    )
                if "gemini_output" in columns:
                    await db.execute(
                        "UPDATE cache SET model_output = gemini_output WHERE model_output = ''"
                    )
                if "can_translate" not in columns:
                    await db.execute(
                        "ALTER TABLE cache ADD COLUMN can_translate TEXT NOT NULL DEFAULT ''"
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
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL DEFAULT '',
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

    async def get_cached_result(
        self, link_hash: str, prompt_hash: str
    ) -> CachedResult | None:
        async with self._acquire_connection_lock():
            async with await self._connect() as db:
                cursor = await db.execute(
                    """
                    SELECT link_hash, prompt_hash, aweme_id, video_url, model_output, can_translate, fps_used, created_at
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
            model_output=row[4],
            can_translate=row[5] or "",
            fps_used=float(row[6]),
            created_at=datetime.fromisoformat(str(row[7])),
        )

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
        async with self._acquire_connection_lock():
            async with await self._connect() as db:
                await db.execute(
                    """
                    INSERT INTO cache (link_hash, prompt_hash, aweme_id, video_url, model_output, can_translate, fps_used)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(link_hash, prompt_hash)
                    DO UPDATE SET
                        aweme_id = excluded.aweme_id,
                        video_url = excluded.video_url,
                        model_output = excluded.model_output,
                        can_translate = excluded.can_translate,
                        fps_used = excluded.fps_used,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        link_hash,
                        prompt_hash,
                        aweme_id,
                        video_url,
                        model_output,
                        can_translate,
                        fps_used,
                    ),
                )
                await db.commit()

    async def save_system_prompt(self, prompt: str) -> None:
        async with self._acquire_connection_lock():
            async with await self._connect() as db:
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
        async with self._acquire_connection_lock():
            async with await self._connect() as db:
                cursor = await db.execute("SELECT content FROM system_prompt WHERE id = 1")
                row = await cursor.fetchone()
                await cursor.close()
        if row is None:
            return None
        return str(row[0])

    async def save_setting(self, key: str, value: str) -> None:
        async with self._acquire_connection_lock():
            async with await self._connect() as db:
                await db.execute(
                    """
                    INSERT INTO app_settings (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key)
                    DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                    """,
                    (key, value),
                )
                await db.commit()

    async def load_setting(self, key: str) -> str | None:
        async with self._acquire_connection_lock():
            async with await self._connect() as db:
                cursor = await db.execute(
                    "SELECT value FROM app_settings WHERE key = ?",
                    (key,),
                )
                row = await cursor.fetchone()
                await cursor.close()
        if row is None:
            return None
        return str(row[0])
