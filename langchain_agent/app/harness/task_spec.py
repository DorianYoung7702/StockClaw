"""Task Specification — machine-executable user financial goal contracts.

A TaskSpec encodes a long-running user objective (e.g. "weekly AAPL earnings
tracking") as a structured record that the CycleRuntime can repeatedly execute
without human intervention.

Usage::

    store = await TaskSpecStore.create()
    spec = await store.create_task(
        user_id="abc",
        goal="每周跟踪AAPL和MSFT财报变化",
        ticker_scope=["AAPL", "MSFT"],
        cadence="0 9 * * MON",
        report_template="fundamental",
    )
    tasks = await store.list_tasks("abc")
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class TaskSpec:
    """A long-running autonomous analysis task contract."""

    task_id: str
    user_id: str
    goal: str
    ticker_scope: list[str]
    kpi_constraints: dict[str, Any]
    cadence: str                        # cron expression or preset
    report_template: str                # "fundamental" | "comparison" | "watchlist_review"
    stop_conditions: dict[str, Any]
    escalation_policy: str              # "email" | "webhook" | "in_app" | "silent"
    status: str = "active"             # "active" | "paused" | "completed" | "failed"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: tuple) -> "TaskSpec":
        """Reconstruct from a SQLite row (column order matches _CREATE_TABLE)."""
        import json
        return cls(
            task_id=row[0],
            user_id=row[1],
            goal=row[2],
            ticker_scope=json.loads(row[3]),
            kpi_constraints=json.loads(row[4]),
            cadence=row[5],
            report_template=row[6],
            stop_conditions=json.loads(row[7]),
            escalation_policy=row[8],
            status=row[9],
            created_at=row[10],
            updated_at=row[11],
        )


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS task_specs (
    task_id            TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL,
    goal               TEXT NOT NULL,
    ticker_scope       TEXT NOT NULL,   -- JSON array
    kpi_constraints    TEXT NOT NULL,   -- JSON object
    cadence            TEXT NOT NULL,
    report_template    TEXT NOT NULL,
    stop_conditions    TEXT NOT NULL,   -- JSON object
    escalation_policy  TEXT NOT NULL DEFAULT 'silent',
    status             TEXT NOT NULL DEFAULT 'active',
    created_at         REAL NOT NULL,
    updated_at         REAL NOT NULL
)
"""

_INDEX = """
CREATE INDEX IF NOT EXISTS idx_task_specs_user
ON task_specs (user_id, status, updated_at DESC)
"""


class TaskSpecStore:
    """Async SQLite-backed CRUD for TaskSpec records."""

    def __init__(self, conn) -> None:
        self._conn = conn

    @classmethod
    async def create(cls, db_path: str | None = None) -> "TaskSpecStore":
        """Open (or create) the task_specs table and return a ready store."""
        import aiosqlite

        if db_path is None:
            from app.config import get_settings
            settings = get_settings()
            db_path = settings.harness_journal_db_path or settings.checkpoint_db_path

        conn = await aiosqlite.connect(db_path)
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute(_CREATE_TABLE)
        await conn.execute(_INDEX)
        await conn.commit()
        logger.info("TaskSpecStore: initialised at %s", db_path)
        return cls(conn)

    async def close(self) -> None:
        await self._conn.close()

    # -- Create ----------------------------------------------------------------

    async def create_task(
        self,
        user_id: str,
        goal: str,
        ticker_scope: list[str],
        cadence: str = "manual",
        report_template: str = "fundamental",
        kpi_constraints: dict[str, Any] | None = None,
        stop_conditions: dict[str, Any] | None = None,
        escalation_policy: str = "silent",
    ) -> TaskSpec:
        """Create and persist a new TaskSpec. Returns the created spec."""
        import json

        spec = TaskSpec(
            task_id=uuid.uuid4().hex[:16],
            user_id=user_id,
            goal=goal,
            ticker_scope=[t.upper().strip() for t in ticker_scope],
            kpi_constraints=kpi_constraints or {"quality_score_min": 7},
            cadence=cadence,
            report_template=report_template,
            stop_conditions=stop_conditions or {"max_cycles": 52},
            escalation_policy=escalation_policy,
        )
        await self._conn.execute(
            """INSERT INTO task_specs
               (task_id, user_id, goal, ticker_scope, kpi_constraints,
                cadence, report_template, stop_conditions, escalation_policy,
                status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                spec.task_id, spec.user_id, spec.goal,
                json.dumps(spec.ticker_scope, ensure_ascii=False),
                json.dumps(spec.kpi_constraints, ensure_ascii=False),
                spec.cadence, spec.report_template,
                json.dumps(spec.stop_conditions, ensure_ascii=False),
                spec.escalation_policy, spec.status,
                spec.created_at, spec.updated_at,
            ),
        )
        await self._conn.commit()
        logger.info("Created task %s for user %s", spec.task_id, user_id)
        return spec

    # -- Read ------------------------------------------------------------------

    async def get_task(self, user_id: str, task_id: str) -> Optional[TaskSpec]:
        """Retrieve a single task by user + task_id. Returns None if not found."""
        cursor = await self._conn.execute(
            "SELECT * FROM task_specs WHERE task_id = ? AND user_id = ?",
            (task_id, user_id),
        )
        row = await cursor.fetchone()
        return TaskSpec.from_row(row) if row else None

    async def list_tasks(
        self, user_id: str, status: str | None = None
    ) -> list[TaskSpec]:
        """List all tasks for a user, optionally filtered by status."""
        if status:
            cursor = await self._conn.execute(
                "SELECT * FROM task_specs WHERE user_id = ? AND status = ? ORDER BY updated_at DESC",
                (user_id, status),
            )
        else:
            cursor = await self._conn.execute(
                "SELECT * FROM task_specs WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            )
        rows = await cursor.fetchall()
        return [TaskSpec.from_row(r) for r in rows]

    # -- Update ----------------------------------------------------------------

    async def update_task(
        self, user_id: str, task_id: str, **fields
    ) -> Optional[TaskSpec]:
        """Update mutable fields on a TaskSpec. Returns updated spec or None."""
        import json

        allowed = {
            "goal", "ticker_scope", "kpi_constraints", "cadence",
            "report_template", "stop_conditions", "escalation_policy", "status",
        }
        json_fields = {"ticker_scope", "kpi_constraints", "stop_conditions"}
        updates = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            updates[k] = json.dumps(v, ensure_ascii=False) if k in json_fields else v

        if not updates:
            return await self.get_task(user_id, task_id)

        updates["updated_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [task_id, user_id]

        await self._conn.execute(
            f"UPDATE task_specs SET {set_clause} WHERE task_id = ? AND user_id = ?",
            values,
        )
        await self._conn.commit()
        return await self.get_task(user_id, task_id)

    # -- Delete ----------------------------------------------------------------

    async def delete_task(self, user_id: str, task_id: str) -> bool:
        """Delete a task. Returns True if a row was removed."""
        cursor = await self._conn.execute(
            "DELETE FROM task_specs WHERE task_id = ? AND user_id = ?",
            (task_id, user_id),
        )
        await self._conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("Deleted task %s for user %s", task_id, user_id)
        return deleted
