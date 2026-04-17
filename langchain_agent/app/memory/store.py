"""Session memory management backed by LangGraph checkpointers.

Lifecycle
---------
1. ``init_checkpointer()`` **must** be awaited once during FastAPI startup
   (inside the ``lifespan`` context manager).  It creates the
   ``AsyncSqliteSaver``, calls ``await saver.setup()`` to ensure the SQLite
   schema exists, and stores the result in a module-level singleton.
2. ``get_checkpointer()`` is a plain sync accessor used by ``dependencies.py``
   and anywhere else that needs the checkpointer.
3. If ``init_checkpointer`` was never called (e.g. during unit tests),
   ``get_checkpointer`` returns a ``MemorySaver`` fallback automatically.

Override ``CHECKPOINT_DB_PATH`` to ``:memory:`` in tests / CI for isolation.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

_checkpointer: Optional[object] = None


def _pid_alive(pid: int) -> bool:
    """Return True if a process with the given PID is still running."""
    try:
        import os
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


async def init_checkpointer() -> None:
    """Initialise the persistent checkpointer (call once at startup).

    Creates ``AsyncSqliteSaver``, runs ``await saver.setup()`` to create
    the checkpoint tables, and stores it as the module singleton.  Falls
    back to ``MemorySaver`` if the SQLite package is missing or the
    connection fails.
    """
    global _checkpointer

    from app.config import get_settings

    settings = get_settings()
    db_path = getattr(settings, "checkpoint_db_path", "")

    if db_path and db_path != ":memory:":
        try:
            import os
            import pathlib
            import aiosqlite
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            db_p = pathlib.Path(str(db_path))
            db_p.parent.mkdir(parents=True, exist_ok=True)

            # ── Pre-flight: delete dirty WAL/SHM before connecting ───────────
            shm = pathlib.Path(str(db_path) + "-shm")
            wal = pathlib.Path(str(db_path) + "-wal")
            dirty = shm.exists() or wal.exists()
            if dirty:
                deleted_all = True
                for p in (shm, wal, db_p):
                    try:
                        if p.exists():
                            p.unlink()
                    except OSError:
                        deleted_all = False

                if not deleted_all:
                    # Files are locked by a still-running reloader/process.
                    # Use a fresh sibling file keyed to this PID — the locked
                    # file will vanish when its owner process finally exits.
                    stem = db_p.stem + f"_{os.getpid()}"
                    db_path = str(db_p.parent / (stem + db_p.suffix))
                    logger.info(
                        "Old DB locked by another process; using fresh file: %s",
                        db_path,
                    )

            # ── Clean up stale PID-based sibling files left by dead processes ─
            import glob
            pattern = str(db_p.parent / (db_p.stem + "_*.db"))
            for old in glob.glob(pattern):
                old_p = pathlib.Path(old)
                try:
                    pid_str = old_p.stem.rsplit("_", 1)[-1]
                    if pid_str.isdigit() and not _pid_alive(int(pid_str)):
                        old_p.unlink(missing_ok=True)
                        logger.debug("Removed stale DB from dead process: %s", old_p)
                except OSError:
                    pass

            conn = await aiosqlite.connect(str(db_path))

            # DELETE journal mode — no .shm/.wal files, safe on Windows
            await conn.execute("PRAGMA journal_mode=DELETE")
            await conn.execute("PRAGMA synchronous=NORMAL")

            saver = AsyncSqliteSaver(conn)
            await saver.setup()
            _checkpointer = saver
            logger.info("Checkpointer: AsyncSqliteSaver at %s (tables ready)", db_path)
            return
        except ImportError:
            logger.warning(
                "langgraph-checkpoint-sqlite not installed; "
                "falling back to MemorySaver. "
                "Run: pip install langgraph-checkpoint-sqlite"
            )
        except Exception as exc:
            logger.warning("AsyncSqliteSaver init failed (%s); using MemorySaver.", exc)

    _checkpointer = MemorySaver()
    logger.info("Checkpointer: MemorySaver (in-process only, sessions not persisted)")


def get_checkpointer():
    """Return the singleton checkpointer.

    Safe to call from sync code.  If ``init_checkpointer`` has not been
    awaited yet (e.g. in tests), a ``MemorySaver`` is created on-the-fly.
    """
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = MemorySaver()
        logger.warning(
            "Checkpointer accessed before init_checkpointer(); "
            "using MemorySaver fallback (sessions not persisted)"
        )
    return _checkpointer


async def close_checkpointer() -> None:
    """Close the persistent checkpointer connection (call once at shutdown)."""
    global _checkpointer
    if _checkpointer is None:
        return
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        if isinstance(_checkpointer, AsyncSqliteSaver) and _checkpointer.conn:
            await _checkpointer.conn.close()
            logger.info("Checkpointer connection closed")
    except Exception as exc:
        logger.warning("Error closing checkpointer: %s", exc)
    _checkpointer = None


def make_thread_config(session_id: Optional[str] = None) -> dict:
    """Build the ``config`` dict that LangGraph expects for checkpointing.

    If *session_id* is ``None`` a new UUID is generated (new conversation).
    """
    sid = session_id or uuid.uuid4().hex
    return {
        "configurable": {
            "thread_id": sid,
        }
    }
