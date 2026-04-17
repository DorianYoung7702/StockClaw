"""User watchlist persistence backed by the same SQLite as checkpoints.

Table schema::

    CREATE TABLE IF NOT EXISTS watchlist (
        user_id  TEXT    NOT NULL,
        ticker   TEXT    NOT NULL,
        note     TEXT    DEFAULT '',
        added_at TEXT    NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (user_id, ticker)
    );
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite

from app.config import get_settings

logger = logging.getLogger(__name__)

_db_path: Optional[str] = None


def _get_db_path() -> str:
    global _db_path
    if _db_path is None:
        settings = get_settings()
        _db_path = str(getattr(settings, "checkpoint_db_path", "atlas_sessions.db"))
    return _db_path


async def _conn() -> aiosqlite.Connection:
    return await aiosqlite.connect(_get_db_path())


async def init_watchlist_table() -> None:
    """Create the watchlist table if it does not exist (call during startup)."""
    db = await _conn()
    try:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                user_id  TEXT NOT NULL,
                ticker   TEXT NOT NULL,
                note     TEXT DEFAULT '',
                added_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, ticker)
            )
            """
        )
        await db.commit()
        logger.info("Watchlist table ready")
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def add_ticker(user_id: str, ticker: str, note: str = "") -> dict[str, Any]:
    """Add a ticker to the user's watchlist. Upsert semantics (update note if exists)."""
    ticker = ticker.upper().strip()
    now = datetime.now(timezone.utc).isoformat()
    db = await _conn()
    try:
        await db.execute(
            """
            INSERT INTO watchlist (user_id, ticker, note, added_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, ticker) DO UPDATE SET note = excluded.note
            """,
            (user_id, ticker, note, now),
        )
        await db.commit()
        return {"user_id": user_id, "ticker": ticker, "note": note, "added_at": now}
    finally:
        await db.close()


async def remove_ticker(user_id: str, ticker: str) -> bool:
    """Remove a ticker. Returns True if a row was actually deleted."""
    ticker = ticker.upper().strip()
    db = await _conn()
    try:
        cursor = await db.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def list_tickers(user_id: str) -> list[dict[str, Any]]:
    """Return all tickers for a user, ordered by added_at desc."""
    db = await _conn()
    try:
        cursor = await db.execute(
            "SELECT ticker, note, added_at FROM watchlist WHERE user_id = ? ORDER BY added_at DESC",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [{"ticker": r[0], "note": r[1], "added_at": r[2]} for r in rows]
    finally:
        await db.close()


async def clear_all(user_id: str) -> int:
    """Remove all tickers for a user. Returns number of rows deleted."""
    db = await _conn()
    try:
        cursor = await db.execute(
            "DELETE FROM watchlist WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()
        return cursor.rowcount
    finally:
        await db.close()


async def update_note(user_id: str, ticker: str, note: str) -> bool:
    """Update the note for an existing watchlist entry. Returns True if row exists."""
    ticker = ticker.upper().strip()
    db = await _conn()
    try:
        cursor = await db.execute(
            "UPDATE watchlist SET note = ? WHERE user_id = ? AND ticker = ?",
            (note, user_id, ticker),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def get_tickers_set(user_id: str) -> set[str]:
    """Return just the ticker symbols as a set (for intersection with strong-stock pool)."""
    items = await list_tickers(user_id)
    return {item["ticker"] for item in items}
