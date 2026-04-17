"""Task Lifecycle Memory — persistent cycle history, KPI trajectory, drift events.

Extends the harness memory tier beyond user preferences (LongTermMemory) to
track the full execution history of autonomous tasks.

Usage::

    mem = await TaskMemory.create()
    await mem.save_cycle(cycle_result)
    history = await mem.get_cycle_history("task_abc", limit=10)
    trajectory = await mem.get_kpi_trajectory("task_abc")
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class CycleResult:
    """Outcome of a single autonomous analysis cycle."""

    cycle_id: str
    task_id: str
    started_at: float
    completed_at: float
    status: str                         # "success" | "partial" | "failed"
    report_markdown: str = ""
    structured_report: dict[str, Any] = field(default_factory=dict)
    kpi_check: dict[str, Any] = field(default_factory=dict)
    quality_score: float = 0.0
    errors: list[str] = field(default_factory=list)
    run_id: str = ""
    product_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: tuple) -> "CycleResult":
        return cls(
            cycle_id=row[0],
            task_id=row[1],
            started_at=row[2],
            completed_at=row[3] or 0.0,
            status=row[4],
            report_markdown=row[5] or "",
            structured_report=json.loads(row[6]) if row[6] else {},
            kpi_check=json.loads(row[7]) if row[7] else {},
            quality_score=row[8] or 0.0,
            errors=json.loads(row[9]) if row[9] else [],
            run_id=row[10] or "",
            product_summary=json.loads(row[11]) if len(row) > 11 and row[11] else {},
        )

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:16]


@dataclass
class DriftIncident:
    """A detected deviation from the user's original task goals."""

    id: str
    task_id: str
    detected_at: float
    signal: str         # ticker_drift, kpi_miss, quality_decay, stale_watchlist, ...
    severity: str       # low, medium, high
    action: str = ""    # re_anchor, refresh_memory, escalate, ...
    resolved: bool = False

    @classmethod
    def from_row(cls, row: tuple) -> "DriftIncident":
        return cls(
            id=row[0],
            task_id=row[1],
            detected_at=row[2],
            signal=row[3],
            severity=row[4],
            action=row[5] or "",
            resolved=bool(row[6]),
        )


# ---------------------------------------------------------------------------
# SQL DDL
# ---------------------------------------------------------------------------

_CREATE_CYCLES = """
CREATE TABLE IF NOT EXISTS task_cycles (
    cycle_id      TEXT PRIMARY KEY,
    task_id       TEXT NOT NULL,
    started_at    REAL NOT NULL,
    completed_at  REAL,
    status        TEXT NOT NULL,
    report_md     TEXT,
    structured    TEXT,
    kpi_check     TEXT,
    quality_score REAL,
    errors        TEXT,
    run_id        TEXT,
    product_summary TEXT
)
"""

_CREATE_KPI = """
CREATE TABLE IF NOT EXISTS kpi_trajectory (
    task_id     TEXT NOT NULL,
    cycle_id    TEXT NOT NULL,
    metric      TEXT NOT NULL,
    value       REAL NOT NULL,
    recorded_at REAL NOT NULL,
    PRIMARY KEY (task_id, cycle_id, metric)
)
"""

_CREATE_DRIFT = """
CREATE TABLE IF NOT EXISTS drift_incidents (
    id          TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL,
    detected_at REAL NOT NULL,
    signal      TEXT NOT NULL,
    severity    TEXT NOT NULL,
    action      TEXT,
    resolved    INTEGER DEFAULT 0
)
"""

_INDEX_CYCLES = """
CREATE INDEX IF NOT EXISTS idx_task_cycles_task
ON task_cycles (task_id, started_at DESC)
"""

_INDEX_KPI = """
CREATE INDEX IF NOT EXISTS idx_kpi_trajectory_task
ON kpi_trajectory (task_id, recorded_at DESC)
"""

_INDEX_DRIFT = """
CREATE INDEX IF NOT EXISTS idx_drift_incidents_task
ON drift_incidents (task_id, detected_at DESC)
"""


# ---------------------------------------------------------------------------
# TaskMemory store
# ---------------------------------------------------------------------------

class TaskMemory:
    """Async SQLite-backed task lifecycle memory."""

    def __init__(self, conn) -> None:
        self._conn = conn

    @classmethod
    async def create(cls, db_path: str | None = None) -> "TaskMemory":
        """Open DB and ensure all task memory tables exist."""
        import aiosqlite

        if db_path is None:
            from app.config import get_settings
            settings = get_settings()
            db_path = settings.harness_journal_db_path or settings.checkpoint_db_path

        conn = await aiosqlite.connect(db_path)
        await conn.execute("PRAGMA journal_mode=WAL")
        for ddl in (_CREATE_CYCLES, _CREATE_KPI, _CREATE_DRIFT,
                     _INDEX_CYCLES, _INDEX_KPI, _INDEX_DRIFT):
            await conn.execute(ddl)
        try:
            await conn.execute("ALTER TABLE task_cycles ADD COLUMN product_summary TEXT")
        except Exception:
            pass
        await conn.commit()
        logger.info("TaskMemory: initialised at %s", db_path)
        return cls(conn)

    async def close(self) -> None:
        await self._conn.close()

    # -- Cycle CRUD ------------------------------------------------------------

    async def save_cycle(self, result: CycleResult) -> None:
        """Persist a completed cycle result."""
        await self._conn.execute(
            """INSERT OR REPLACE INTO task_cycles
               (cycle_id, task_id, started_at, completed_at, status,
                report_md, structured, kpi_check, quality_score, errors, run_id, product_summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result.cycle_id, result.task_id,
                result.started_at, result.completed_at, result.status,
                result.report_markdown,
                json.dumps(result.structured_report, ensure_ascii=False),
                json.dumps(result.kpi_check, ensure_ascii=False),
                result.quality_score,
                json.dumps(result.errors, ensure_ascii=False),
                result.run_id,
                json.dumps(result.product_summary, ensure_ascii=False),
            ),
        )
        # Also write KPI trajectory entries
        now = time.time()
        kpi_rows = [
            (result.task_id, result.cycle_id, "quality_score",
             result.quality_score, now),
        ]
        for metric, value in result.kpi_check.items():
            if isinstance(value, (int, float)):
                kpi_rows.append(
                    (result.task_id, result.cycle_id, metric, value, now)
                )
        await self._conn.executemany(
            """INSERT OR REPLACE INTO kpi_trajectory
               (task_id, cycle_id, metric, value, recorded_at)
               VALUES (?, ?, ?, ?, ?)""",
            kpi_rows,
        )
        await self._conn.commit()
        logger.info("Saved cycle %s for task %s (status=%s)",
                     result.cycle_id, result.task_id, result.status)

    async def get_cycle_history(
        self, task_id: str, limit: int = 10
    ) -> list[CycleResult]:
        """Retrieve recent cycles for a task, newest first."""
        cursor = await self._conn.execute(
            "SELECT * FROM task_cycles WHERE task_id = ? ORDER BY started_at DESC LIMIT ?",
            (task_id, limit),
        )
        rows = await cursor.fetchall()
        return [CycleResult.from_row(r) for r in rows]

    async def get_latest_summary(self, task_id: str) -> Optional[str]:
        """Get the most recent cycle's report markdown (for injection into next cycle)."""
        cursor = await self._conn.execute(
            "SELECT report_md FROM task_cycles WHERE task_id = ? AND status IN ('success', 'partial') "
            "ORDER BY started_at DESC LIMIT 1",
            (task_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def get_completed_cycle_count(self, task_id: str) -> int:
        """Count completed cycles for stop-condition checks."""
        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM task_cycles WHERE task_id = ?",
            (task_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    # -- KPI trajectory --------------------------------------------------------

    async def get_kpi_trajectory(
        self, task_id: str, metric: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """KPI scores over time for trend analysis."""
        if metric:
            cursor = await self._conn.execute(
                "SELECT cycle_id, metric, value, recorded_at FROM kpi_trajectory "
                "WHERE task_id = ? AND metric = ? ORDER BY recorded_at DESC LIMIT ?",
                (task_id, metric, limit),
            )
        else:
            cursor = await self._conn.execute(
                "SELECT cycle_id, metric, value, recorded_at FROM kpi_trajectory "
                "WHERE task_id = ? ORDER BY recorded_at DESC LIMIT ?",
                (task_id, limit),
            )
        rows = await cursor.fetchall()
        return [
            {"cycle_id": r[0], "metric": r[1], "value": r[2], "recorded_at": r[3]}
            for r in rows
        ]

    # -- Drift incidents -------------------------------------------------------

    async def save_drift_incident(self, incident: DriftIncident) -> None:
        """Record a drift detection event."""
        await self._conn.execute(
            """INSERT OR REPLACE INTO drift_incidents
               (id, task_id, detected_at, signal, severity, action, resolved)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                incident.id, incident.task_id, incident.detected_at,
                incident.signal, incident.severity, incident.action,
                int(incident.resolved),
            ),
        )
        await self._conn.commit()
        logger.info("Drift incident %s recorded for task %s: %s (%s)",
                     incident.id, incident.task_id, incident.signal, incident.severity)

    async def get_drift_incidents(
        self, task_id: str, unresolved_only: bool = False, limit: int = 20
    ) -> list[DriftIncident]:
        """Retrieve drift incidents for a task."""
        if unresolved_only:
            cursor = await self._conn.execute(
                "SELECT * FROM drift_incidents WHERE task_id = ? AND resolved = 0 "
                "ORDER BY detected_at DESC LIMIT ?",
                (task_id, limit),
            )
        else:
            cursor = await self._conn.execute(
                "SELECT * FROM drift_incidents WHERE task_id = ? "
                "ORDER BY detected_at DESC LIMIT ?",
                (task_id, limit),
            )
        rows = await cursor.fetchall()
        return [DriftIncident.from_row(r) for r in rows]

    async def resolve_drift(self, incident_id: str) -> bool:
        """Mark a drift incident as resolved."""
        cursor = await self._conn.execute(
            "UPDATE drift_incidents SET resolved = 1 WHERE id = ?",
            (incident_id,),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    # -- Escalation log --------------------------------------------------------

    async def get_escalation_log(self, task_id: str, limit: int = 20) -> list[dict]:
        """Retrieve escalation-relevant events (high-severity drifts + failed cycles)."""
        cursor = await self._conn.execute(
            """SELECT 'drift' AS source, id, detected_at AS ts, signal AS detail, severity
               FROM drift_incidents WHERE task_id = ? AND severity = 'high'
               UNION ALL
               SELECT 'cycle_fail', cycle_id, started_at, status, 'high'
               FROM task_cycles WHERE task_id = ? AND status = 'failed'
               ORDER BY ts DESC LIMIT ?""",
            (task_id, task_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            {"source": r[0], "id": r[1], "timestamp": r[2],
             "detail": r[3], "severity": r[4]}
            for r in rows
        ]
