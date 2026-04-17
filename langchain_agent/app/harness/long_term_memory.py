"""Cross-session Long-term Memory — the agent's persistent "filesystem".

Stores user preferences, analysis history summaries, and learned patterns
in SQLite so the agent can recall context from previous sessions.

Three memory layers in the harness:
    Context Window  → what the model sees right now (managed by context.py)
    Session Memory  → conversation history within one session (LangGraph checkpoint)
    Long-term Memory → this module: persists across sessions

Usage::

    ltm = await LongTermMemory.create()
    await ltm.remember("user_abc", "preference", "market", "偏好美股科技股")
    entries = await ltm.recall("user_abc", "preference", top_k=5)
    context_str = await ltm.get_user_context("user_abc")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    user_id: str
    category: str
    key: str
    content: str
    created_at: float
    updated_at: float
    access_count: int


class LongTermMemory:
    """Async SQLite-backed cross-session memory store."""

    def __init__(self, conn) -> None:
        self._conn = conn

    @classmethod
    async def create(cls, db_path: str | None = None) -> "LongTermMemory":
        """Create the store, ensuring the ``user_memory`` table exists."""
        import aiosqlite

        if db_path is None:
            from app.config import get_settings
            settings = get_settings()
            db_path = settings.harness_journal_db_path or settings.checkpoint_db_path

        conn = await aiosqlite.connect(db_path)
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_memory (
                user_id      TEXT NOT NULL,
                category     TEXT NOT NULL,
                key          TEXT NOT NULL,
                content      TEXT NOT NULL,
                created_at   REAL NOT NULL,
                updated_at   REAL NOT NULL,
                access_count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, category, key)
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_memory_user_cat
            ON user_memory (user_id, category, updated_at DESC)
        """)
        await conn.commit()
        logger.info("LongTermMemory: initialised at %s", db_path)
        return cls(conn)

    # -- Write -------------------------------------------------------------

    async def remember(
        self,
        user_id: str,
        category: str,
        key: str,
        content: str,
    ) -> None:
        """Store or update a memory entry."""
        now = time.time()
        await self._conn.execute("""
            INSERT INTO user_memory (user_id, category, key, content, created_at, updated_at, access_count)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(user_id, category, key) DO UPDATE SET
                content = excluded.content,
                updated_at = excluded.updated_at,
                access_count = access_count + 1
        """, (user_id, category, key, content, now, now))
        await self._conn.commit()
        logger.debug("LongTermMemory: remembered [%s/%s/%s]", user_id, category, key)

    # -- Read --------------------------------------------------------------

    async def recall(
        self,
        user_id: str,
        category: str | None = None,
        top_k: int = 5,
    ) -> list[MemoryEntry]:
        """Retrieve the most recent memories for a user.

        Ordered by recency (updated_at DESC), with access_count as tiebreaker.
        Bumps access_count for returned entries.
        """
        if category:
            cursor = await self._conn.execute(
                "SELECT user_id, category, key, content, created_at, updated_at, access_count "
                "FROM user_memory WHERE user_id = ? AND category = ? "
                "ORDER BY updated_at DESC, access_count DESC LIMIT ?",
                (user_id, category, top_k),
            )
        else:
            cursor = await self._conn.execute(
                "SELECT user_id, category, key, content, created_at, updated_at, access_count "
                "FROM user_memory WHERE user_id = ? "
                "ORDER BY updated_at DESC, access_count DESC LIMIT ?",
                (user_id, top_k),
            )

        rows = await cursor.fetchall()
        entries = [MemoryEntry(*row) for row in rows]

        # Bump access counts
        if entries:
            keys = [(user_id, e.category, e.key) for e in entries]
            await self._conn.executemany(
                "UPDATE user_memory SET access_count = access_count + 1 "
                "WHERE user_id = ? AND category = ? AND key = ?",
                keys,
            )
            await self._conn.commit()

        return entries

    async def get_user_context(self, user_id: str, max_entries: int = 10) -> str:
        """Assemble a system-prompt-friendly context string from user memories.

        Returns a structured text block that can be injected into the system
        prompt to personalise the agent's responses.

        Probabilistically cleans up stale entries (~10 % of calls) to prevent
        unbounded table growth.
        """
        # --- Auto-cleanup: ~10 % of calls trigger stale entry removal ---
        import random
        if random.random() < 0.10:
            removed = await self.forget_old(user_id, max_age_days=90)
            if removed:
                logger.info("LongTermMemory: auto-cleaned %d stale entries for %s", removed, user_id)

        entries = await self.recall(user_id, top_k=max_entries)
        if not entries:
            return ""

        sections: dict[str, list[str]] = {}
        for e in entries:
            sections.setdefault(e.category, []).append(f"- {e.key}: {e.content}")

        parts: list[str] = ["[用户历史记忆]"]
        category_labels = {
            "preference": "偏好设置",
            "analysis_history": "历史分析",
            "learned_pattern": "行为模式",
        }
        for cat, items in sections.items():
            label = category_labels.get(cat, cat)
            parts.append(f"\n### {label}")
            parts.extend(items)

        return "\n".join(parts)

    # -- Delete ------------------------------------------------------------

    async def forget(self, user_id: str, category: str, key: str) -> bool:
        """Delete a specific memory entry."""
        cursor = await self._conn.execute(
            "DELETE FROM user_memory WHERE user_id = ? AND category = ? AND key = ?",
            (user_id, category, key),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def forget_old(self, user_id: str, max_age_days: int = 90) -> int:
        """Delete memories older than *max_age_days*."""
        cutoff = time.time() - (max_age_days * 86400)
        cursor = await self._conn.execute(
            "DELETE FROM user_memory WHERE user_id = ? AND updated_at < ?",
            (user_id, cutoff),
        )
        await self._conn.commit()
        return cursor.rowcount

    # -- Stats (for metrics dashboard) ------------------------------------

    async def count(self, user_id: str) -> dict[str, int]:
        """Return per-category memory counts for a user."""
        cursor = await self._conn.execute(
            "SELECT category, COUNT(*) FROM user_memory WHERE user_id = ? GROUP BY category",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}

    async def close(self) -> None:
        await self._conn.close()
