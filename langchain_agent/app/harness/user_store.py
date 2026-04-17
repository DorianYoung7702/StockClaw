"""Lightweight User Account Persistence.

Maintains a ``users`` table in SQLite for tracking user identity,
session counts, and analysis counts.  No passwords — identity is
derived from the API token.

The store is designed to be transparent: existing code doesn't need
to know about user_id; the harness injects it at the API layer.

Usage::

    store = await UserStore.create()          # auto-creates table
    user = await store.upsert("token_abc")    # creates or bumps last_active
    await store.increment_analyses("token_abc")
    stats = await store.get_stats("token_abc")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class UserRecord:
    user_id: str
    display_name: str
    created_at: float
    last_active: float
    session_count: int
    total_analyses: int


class UserStore:
    """Async SQLite-backed user account store."""

    def __init__(self, conn) -> None:
        self._conn = conn

    @classmethod
    async def create(cls, db_path: str | None = None) -> "UserStore":
        """Create the store, ensuring the ``users`` table exists.

        If *db_path* is None, uses the same DB as the checkpoint store.
        """
        import aiosqlite

        if db_path is None:
            from app.config import get_settings
            settings = get_settings()
            db_path = settings.harness_journal_db_path or settings.checkpoint_db_path

        conn = await aiosqlite.connect(db_path)
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id        TEXT PRIMARY KEY,
                display_name   TEXT DEFAULT '',
                created_at     REAL NOT NULL,
                last_active    REAL NOT NULL,
                session_count  INTEGER DEFAULT 0,
                total_analyses INTEGER DEFAULT 0
            )
        """)
        await conn.commit()
        logger.info("UserStore: initialised at %s", db_path)
        return cls(conn)

    async def upsert(self, user_id: str, display_name: str = "") -> UserRecord:
        """Create or update a user record; bumps ``last_active`` and ``session_count``."""
        now = time.time()
        await self._conn.execute("""
            INSERT INTO users (user_id, display_name, created_at, last_active, session_count, total_analyses)
            VALUES (?, ?, ?, ?, 1, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                last_active = ?,
                session_count = session_count + 1
        """, (user_id, display_name, now, now, now))
        await self._conn.commit()
        return await self.get(user_id)  # type: ignore[return-value]

    async def get(self, user_id: str) -> Optional[UserRecord]:
        """Fetch a user by ID."""
        cursor = await self._conn.execute(
            "SELECT user_id, display_name, created_at, last_active, session_count, total_analyses "
            "FROM users WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return UserRecord(*row)

    async def increment_analyses(self, user_id: str) -> None:
        """Increment the ``total_analyses`` counter for a user."""
        await self._conn.execute(
            "UPDATE users SET total_analyses = total_analyses + 1 WHERE user_id = ?",
            (user_id,),
        )
        await self._conn.commit()

    async def get_stats(self, user_id: str) -> dict[str, Any]:
        """Return user statistics suitable for API responses."""
        user = await self.get(user_id)
        if user is None:
            return {"error": "user_not_found"}
        return {
            "user_id": user.user_id,
            "display_name": user.display_name,
            "member_since": user.created_at,
            "last_active": user.last_active,
            "session_count": user.session_count,
            "total_analyses": user.total_analyses,
        }

    async def list_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """List all users (admin/metrics use)."""
        cursor = await self._conn.execute(
            "SELECT user_id, display_name, created_at, last_active, session_count, total_analyses "
            "FROM users ORDER BY last_active DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "user_id": r[0], "display_name": r[1],
                "created_at": r[2], "last_active": r[3],
                "session_count": r[4], "total_analyses": r[5],
            }
            for r in rows
        ]

    async def close(self) -> None:
        await self._conn.close()
