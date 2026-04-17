from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from app.harness.scheduler import TaskScheduler
from app.harness.task_memory import TaskMemory
from app.harness.task_spec import TaskSpecStore
from app.memory.watchlist import list_tickers

logger = logging.getLogger(__name__)


@dataclass
class ResidentAgentRecord:
    user_id: str
    task_id: str = ""
    enabled: bool = False
    interval_seconds: int = 900
    status: str = "stopped"
    last_run_at: float = 0.0
    last_error: str = ""
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> "ResidentAgentRecord":
        return cls(
            user_id=row[0],
            task_id=row[1] or "",
            enabled=bool(row[2]),
            interval_seconds=int(row[3] or 900),
            status=row[4] or "stopped",
            last_run_at=float(row[5] or 0.0),
            last_error=row[6] or "",
            updated_at=float(row[7] or 0.0),
        )


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS resident_agents (
    user_id           TEXT PRIMARY KEY,
    task_id           TEXT NOT NULL DEFAULT '',
    enabled           INTEGER NOT NULL DEFAULT 0,
    interval_seconds  INTEGER NOT NULL DEFAULT 900,
    status            TEXT NOT NULL DEFAULT 'stopped',
    last_run_at       REAL NOT NULL DEFAULT 0,
    last_error        TEXT NOT NULL DEFAULT '',
    updated_at        REAL NOT NULL
)
"""


class ResidentAgentStore:
    def __init__(self, conn) -> None:
        self._conn = conn

    @classmethod
    async def create(cls, db_path: str | None = None) -> "ResidentAgentStore":
        import aiosqlite

        if db_path is None:
            from app.config import get_settings

            settings = get_settings()
            db_path = settings.harness_journal_db_path or settings.checkpoint_db_path

        conn = await aiosqlite.connect(db_path)
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute(_CREATE_TABLE)
        await conn.commit()
        return cls(conn)

    async def close(self) -> None:
        await self._conn.close()

    async def get(self, user_id: str) -> Optional[ResidentAgentRecord]:
        cursor = await self._conn.execute(
            "SELECT user_id, task_id, enabled, interval_seconds, status, last_run_at, last_error, updated_at FROM resident_agents WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return ResidentAgentRecord.from_row(row) if row else None

    async def list_enabled(self) -> list[ResidentAgentRecord]:
        cursor = await self._conn.execute(
            "SELECT user_id, task_id, enabled, interval_seconds, status, last_run_at, last_error, updated_at FROM resident_agents WHERE enabled = 1 ORDER BY updated_at DESC"
        )
        rows = await cursor.fetchall()
        return [ResidentAgentRecord.from_row(row) for row in rows]

    async def upsert(
        self,
        user_id: str,
        *,
        task_id: str | None = None,
        enabled: bool | None = None,
        interval_seconds: int | None = None,
        status: str | None = None,
        last_run_at: float | None = None,
        last_error: str | None = None,
    ) -> ResidentAgentRecord:
        existing = await self.get(user_id)
        record = existing or ResidentAgentRecord(user_id=user_id)
        if task_id is not None:
            record.task_id = task_id
        if enabled is not None:
            record.enabled = enabled
        if interval_seconds is not None:
            record.interval_seconds = max(60, int(interval_seconds))
        if status is not None:
            record.status = status
        if last_run_at is not None:
            record.last_run_at = last_run_at
        if last_error is not None:
            record.last_error = last_error
        record.updated_at = time.time()
        await self._conn.execute(
            """
            INSERT INTO resident_agents (
                user_id, task_id, enabled, interval_seconds, status, last_run_at, last_error, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                task_id = excluded.task_id,
                enabled = excluded.enabled,
                interval_seconds = excluded.interval_seconds,
                status = excluded.status,
                last_run_at = excluded.last_run_at,
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            (
                record.user_id,
                record.task_id,
                int(record.enabled),
                record.interval_seconds,
                record.status,
                record.last_run_at,
                record.last_error,
                record.updated_at,
            ),
        )
        await self._conn.commit()
        return record


class ResidentAgentService:
    def __init__(self, *, cycle_timeout: int = 300, default_interval_seconds: int = 300) -> None:
        self._scheduler = TaskScheduler(cycle_timeout=cycle_timeout)
        self._default_interval_seconds = max(60, default_interval_seconds)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def start(self) -> None:
        store = await ResidentAgentStore.create()
        enabled = await store.list_enabled()
        await store.close()
        for record in enabled:
            await self._spawn_loop(record.user_id)

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def get_status(self, user_id: str, *, cycle_limit: int = 10) -> dict[str, Any]:
        store = await ResidentAgentStore.create()
        record = await store.get(user_id)
        await store.close()
        if record is None:
            record = ResidentAgentRecord(
                user_id=user_id,
                interval_seconds=self._default_interval_seconds,
            )

        watchlist = await list_tickers(user_id)
        recent_cycles: list[dict[str, Any]] = []
        latest_cycle: dict[str, Any] | None = None
        if record.task_id:
            mem = await TaskMemory.create()
            cycles = await mem.get_cycle_history(record.task_id, limit=cycle_limit)
            await mem.close()
            recent_cycles = [c.to_dict() for c in cycles]
            latest_cycle = recent_cycles[0] if recent_cycles else None

        return {
            **record.to_dict(),
            "running": user_id in self._tasks and not self._tasks[user_id].done(),
            "watchlist": watchlist,
            "watchlist_count": len(watchlist),
            "recent_cycles": recent_cycles,
            "latest_cycle": latest_cycle,
        }

    async def start_user(
        self,
        user_id: str,
        *,
        interval_seconds: int | None = None,
        run_immediately: bool = True,
    ) -> dict[str, Any]:
        interval = interval_seconds or self._default_interval_seconds
        store = await ResidentAgentStore.create()
        record = await store.upsert(
            user_id,
            enabled=True,
            interval_seconds=interval,
            status="starting",
            last_error="",
        )
        await store.close()
        await self._sync_task(user_id, enabled=True, interval_seconds=record.interval_seconds)
        if run_immediately:
            try:
                await self.run_once(user_id, require_enabled=True)
            except Exception as exc:
                logger.warning(
                    "Resident agent immediate run failed for %s during enable: %s",
                    user_id,
                    exc,
                )
        await self._spawn_loop(user_id, restart=True)
        return await self.get_status(user_id)

    async def stop_user(self, user_id: str) -> dict[str, Any]:
        task = self._tasks.pop(user_id, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        store = await ResidentAgentStore.create()
        record = await store.get(user_id)
        await store.upsert(user_id, enabled=False, status="stopped")
        await store.close()

        if record and record.task_id:
            task_store = await TaskSpecStore.create()
            await task_store.update_task(user_id, record.task_id, status="paused")
            await task_store.close()

        return await self.get_status(user_id)

    async def run_once(self, user_id: str, *, require_enabled: bool = False) -> dict[str, Any]:
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            store = await ResidentAgentStore.create()
            record = await store.get(user_id)
            if record is None:
                record = await store.upsert(
                    user_id,
                    enabled=False,
                    interval_seconds=self._default_interval_seconds,
                    status="stopped",
                )
            if require_enabled and not record.enabled:
                await store.close()
                return await self.get_status(user_id)
            record = await store.upsert(user_id, status="running", last_error="")
            await store.close()

            try:
                task_id = await self._sync_task(
                    user_id,
                    enabled=record.enabled,
                    interval_seconds=record.interval_seconds,
                    task_status_override="active",
                )
                if not task_id:
                    store = await ResidentAgentStore.create()
                    await store.upsert(
                        user_id,
                        status="waiting_watchlist",
                        last_error="",
                        last_run_at=time.time(),
                    )
                    await store.close()
                    return await self.get_status(user_id)

                result = await self._scheduler.force_run(task_id, user_id)
                error_text = ""
                status = "idle"
                if result.get("error"):
                    error_text = str(result["error"])
                    status = "error"
                elif result.get("errors"):
                    error_text = "; ".join(str(e) for e in result["errors"])
                if not record.enabled and task_id:
                    task_store = await TaskSpecStore.create()
                    await task_store.update_task(user_id, task_id, status="paused")
                    await task_store.close()
                store = await ResidentAgentStore.create()
                await store.upsert(
                    user_id,
                    task_id=task_id,
                    status=status,
                    last_run_at=time.time(),
                    last_error=error_text,
                )
                await store.close()
            except Exception as exc:
                store = await ResidentAgentStore.create()
                await store.upsert(
                    user_id,
                    status="error",
                    last_error=str(exc),
                    last_run_at=time.time(),
                )
                await store.close()
                raise

        return await self.get_status(user_id)

    async def sync_watchlist(self, user_id: str) -> dict[str, Any]:
        await self._sync_task(user_id)
        return await self.get_status(user_id)

    async def update_settings(
        self,
        user_id: str,
        *,
        interval_seconds: int | None = None,
    ) -> dict[str, Any]:
        store = await ResidentAgentStore.create()
        record = await store.get(user_id)
        if record is None:
            record = await store.upsert(
                user_id,
                enabled=False,
                interval_seconds=interval_seconds or self._default_interval_seconds,
                status="stopped",
            )
        elif interval_seconds is not None:
            record = await store.upsert(
                user_id,
                interval_seconds=interval_seconds,
            )
        await store.close()
        await self._sync_task(
            user_id,
            enabled=record.enabled,
            interval_seconds=record.interval_seconds,
        )
        if record.enabled:
            await self._spawn_loop(user_id, restart=True)
        return await self.get_status(user_id)

    async def _spawn_loop(self, user_id: str, *, restart: bool = False) -> None:
        if restart:
            task = self._tasks.pop(user_id, None)
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        current = self._tasks.get(user_id)
        if current and not current.done():
            return
        self._tasks[user_id] = asyncio.create_task(self._loop_user(user_id))

    async def _loop_user(self, user_id: str) -> None:
        try:
            while True:
                store = await ResidentAgentStore.create()
                record = await store.get(user_id)
                await store.close()
                if record is None or not record.enabled:
                    return
                now = time.time()
                next_run_at = (record.last_run_at or 0.0) + max(60, record.interval_seconds)
                sleep_for = next_run_at - now if record.last_run_at else 0.0
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                    continue
                try:
                    await self.run_once(user_id, require_enabled=True)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Resident agent run failed for %s: %s", user_id, exc)
        except asyncio.CancelledError:
            raise
        finally:
            self._tasks.pop(user_id, None)

    async def _sync_task(
        self,
        user_id: str,
        *,
        enabled: bool | None = None,
        interval_seconds: int | None = None,
        task_status_override: str | None = None,
    ) -> str:
        store = await ResidentAgentStore.create()
        record = await store.get(user_id)
        if record is None:
            record = await store.upsert(
                user_id,
                enabled=bool(enabled) if enabled is not None else False,
                interval_seconds=interval_seconds or self._default_interval_seconds,
            )
        tickers = [item["ticker"] for item in await list_tickers(user_id)]
        if not tickers:
            next_status = "waiting_watchlist" if record.enabled or enabled else "stopped"
            await store.upsert(
                user_id,
                enabled=record.enabled if enabled is None else enabled,
                interval_seconds=interval_seconds or record.interval_seconds,
                status=next_status,
            )
            await store.close()
            if record.task_id:
                task_store = await TaskSpecStore.create()
                await task_store.update_task(user_id, record.task_id, status="paused", ticker_scope=[])
                await task_store.close()
            return ""

        task_store = await TaskSpecStore.create()
        task_id = record.task_id
        spec = await task_store.get_task(user_id, task_id) if task_id else None
        task_status = task_status_override or ("active" if (enabled if enabled is not None else record.enabled) else "paused")
        cadence = f"resident:{interval_seconds or record.interval_seconds}"
        if spec is None:
            spec = await task_store.create_task(
                user_id=user_id,
                goal="持续巡检观察组并输出投研更新",
                ticker_scope=tickers,
                cadence=cadence,
                report_template="watchlist_review",
                kpi_constraints={"quality_score_min": 7},
                stop_conditions={"max_cycles": 1000000},
                escalation_policy="in_app",
            )
            task_id = spec.task_id
        else:
            await task_store.update_task(
                user_id,
                task_id,
                goal="持续巡检观察组并输出投研更新",
                ticker_scope=tickers,
                cadence=cadence,
                report_template="watchlist_review",
                kpi_constraints={"quality_score_min": 7},
                stop_conditions={"max_cycles": 1000000},
                escalation_policy="in_app",
                status=task_status,
            )
        await task_store.close()
        await store.upsert(
            user_id,
            task_id=task_id,
            enabled=record.enabled if enabled is None else enabled,
            interval_seconds=interval_seconds or record.interval_seconds,
            status="idle" if task_status == "active" else "stopped",
        )
        await store.close()
        return task_id
