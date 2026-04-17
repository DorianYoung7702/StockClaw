"""Metrics Aggregator — resume-ready quantitative indicators.

Reads from ``run_journal`` and ``users`` tables to produce aggregated
metrics suitable for both the API dashboard and resume bullet points.

Target metrics:
    - End-to-end latency P50 / P95
    - First Completion Rate (FCR) — runs with zero recovery events
    - Context compaction savings (tokens saved)
    - Auto-recovery rate — L1–L3 / total errors
    - Token utilisation efficiency
    - Report quality score (reflect_node average)
    - User retention (session counts)
    - Circuit breaker trip frequency

Usage::

    agg = await MetricsAggregator.create()
    dashboard = await agg.dashboard()
    # → dict with all metrics for API / frontend
"""

from __future__ import annotations

import json
import logging
import statistics
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MetricsAggregator:
    """Reads journal + user data and produces aggregated metrics."""

    def __init__(self, conn) -> None:
        self._conn = conn

    @classmethod
    async def create(cls, db_path: str | None = None) -> "MetricsAggregator":
        import aiosqlite

        if db_path is None:
            from app.config import get_settings
            settings = get_settings()
            db_path = settings.harness_journal_db_path or settings.checkpoint_db_path

        conn = await aiosqlite.connect(db_path)
        return cls(conn)

    # -- Individual metric queries -----------------------------------------

    async def _get_run_latencies(self) -> list[float]:
        """Get per-run total latency in ms."""
        cursor = await self._conn.execute("""
            SELECT run_id,
                   (MAX(created_at) - MIN(created_at)) * 1000 AS duration_ms
            FROM run_journal
            GROUP BY run_id
            HAVING COUNT(*) > 1
        """)
        rows = await cursor.fetchall()
        return [row[1] for row in rows if row[1] and row[1] > 0]

    async def _get_fcr(self) -> dict[str, Any]:
        """First Completion Rate — runs with zero recovery/error events."""
        cursor = await self._conn.execute("""
            SELECT run_id, COUNT(*) AS total_entries,
                   SUM(CASE WHEN entry_json LIKE '%"recovery"%' THEN 1 ELSE 0 END) AS recovery_count,
                   SUM(CASE WHEN entry_json LIKE '%"error"%' THEN 1 ELSE 0 END) AS error_count
            FROM run_journal
            GROUP BY run_id
        """)
        rows = await cursor.fetchall()
        total_runs = len(rows)
        clean_runs = sum(1 for r in rows if r[2] == 0 and r[3] == 0)
        return {
            "total_runs": total_runs,
            "clean_runs": clean_runs,
            "fcr": round(clean_runs / total_runs, 3) if total_runs > 0 else 0.0,
        }

    async def _get_compaction_savings(self) -> dict[str, Any]:
        """Total tokens saved by compaction."""
        cursor = await self._conn.execute("""
            SELECT entry_json FROM run_journal
            WHERE entry_json LIKE '%"compaction"%'
        """)
        rows = await cursor.fetchall()
        total_saved = 0
        compaction_count = 0
        for row in rows:
            try:
                data = json.loads(row[0])
                payload = data.get("payload", {})
                total_saved += payload.get("saved_tokens", 0)
                compaction_count += 1
            except (json.JSONDecodeError, TypeError):
                pass
        return {
            "compaction_events": compaction_count,
            "total_tokens_saved": total_saved,
        }

    async def _get_recovery_stats(self) -> dict[str, Any]:
        """Recovery rate by level."""
        cursor = await self._conn.execute("""
            SELECT entry_json FROM run_journal
            WHERE entry_json LIKE '%"recovery"%'
               OR entry_json LIKE '%"error"%'
        """)
        rows = await cursor.fetchall()
        total_errors = 0
        auto_recovered = 0  # L1-L3
        escalated = 0       # L4
        by_level = {1: 0, 2: 0, 3: 0, 4: 0}

        for row in rows:
            try:
                data = json.loads(row[0])
                event_type = data.get("event_type", "")
                payload = data.get("payload", {})
                if event_type == "error":
                    total_errors += 1
                elif event_type == "recovery":
                    level = payload.get("level", 1)
                    by_level[level] = by_level.get(level, 0) + 1
                    if level <= 3:
                        auto_recovered += 1
                    else:
                        escalated += 1
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            "total_errors": total_errors,
            "auto_recovered": auto_recovered,
            "escalated": escalated,
            "auto_recovery_rate": round(auto_recovered / max(total_errors, 1), 3),
            "by_level": by_level,
        }

    async def _get_token_usage(self) -> dict[str, Any]:
        """Aggregate token usage across all runs."""
        cursor = await self._conn.execute("""
            SELECT entry_json FROM run_journal
            WHERE entry_json LIKE '%token_usage%'
        """)
        rows = await cursor.fetchall()
        total_prompt = 0
        total_completion = 0
        for row in rows:
            try:
                data = json.loads(row[0])
                usage = data.get("token_usage", {})
                total_prompt += usage.get("prompt_tokens", 0)
                total_completion += usage.get("completion_tokens", 0)
            except (json.JSONDecodeError, TypeError):
                pass
        total = total_prompt + total_completion
        return {
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total,
            "efficiency": round(total_completion / max(total, 1), 3),
        }

    async def _get_quality_scores(self) -> dict[str, Any]:
        """Report quality scores from reflect_node (stored in journal payload)."""
        cursor = await self._conn.execute("""
            SELECT entry_json FROM run_journal
            WHERE entry_json LIKE '%reflection_score%'
        """)
        rows = await cursor.fetchall()
        scores: list[float] = []
        for row in rows:
            try:
                data = json.loads(row[0])
                score = data.get("payload", {}).get("reflection_score")
                if score is not None:
                    scores.append(float(score))
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        if not scores:
            return {"count": 0, "mean": 0, "median": 0, "p25": 0, "p75": 0}
        return {
            "count": len(scores),
            "mean": round(statistics.mean(scores), 2),
            "median": round(statistics.median(scores), 2),
            "p25": round(sorted(scores)[len(scores) // 4], 2) if len(scores) >= 4 else 0,
            "p75": round(sorted(scores)[3 * len(scores) // 4], 2) if len(scores) >= 4 else 0,
        }

    async def _get_user_stats(self) -> dict[str, Any]:
        """User-level aggregate stats."""
        try:
            cursor = await self._conn.execute(
                "SELECT COUNT(*), SUM(session_count), SUM(total_analyses) FROM users"
            )
            row = await cursor.fetchone()
            if row:
                return {
                    "total_users": row[0] or 0,
                    "total_sessions": row[1] or 0,
                    "total_analyses": row[2] or 0,
                }
        except Exception:
            pass  # table may not exist yet
        return {"total_users": 0, "total_sessions": 0, "total_analyses": 0}

    # -- Dashboard (all metrics) -------------------------------------------

    async def dashboard(self) -> dict[str, Any]:
        """Return all metrics in a single dict for the API."""
        latencies = await self._get_run_latencies()
        p50 = round(statistics.median(latencies), 1) if latencies else 0
        p95 = round(sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) >= 20 else (max(latencies) if latencies else 0), 1)

        fcr = await self._get_fcr()
        compaction = await self._get_compaction_savings()
        recovery = await self._get_recovery_stats()
        tokens = await self._get_token_usage()
        quality = await self._get_quality_scores()
        users = await self._get_user_stats()

        return {
            "latency": {
                "p50_ms": p50,
                "p95_ms": p95,
                "sample_count": len(latencies),
            },
            "first_completion_rate": fcr,
            "compaction": compaction,
            "recovery": recovery,
            "token_usage": tokens,
            "quality_scores": quality,
            "users": users,
            # Resume-friendly summaries
            "resume_bullets": self._format_resume_bullets(
                p50, p95, fcr, compaction, recovery, tokens, quality, users,
            ),
        }

    @staticmethod
    def _format_resume_bullets(
        p50, p95, fcr, compaction, recovery, tokens, quality, users,
    ) -> list[str]:
        """Generate resume-ready bullet point strings."""
        bullets: list[str] = []
        if p95 > 0:
            bullets.append(f"Agent pipeline latency P95={p95:.0f}ms, P50={p50:.0f}ms")
        if fcr.get("total_runs", 0) > 0:
            bullets.append(
                f"First Completion Rate {fcr['fcr']*100:.0f}% "
                f"({fcr['clean_runs']}/{fcr['total_runs']} runs)"
            )
        if compaction.get("total_tokens_saved", 0) > 0:
            bullets.append(
                f"Context compaction saved {compaction['total_tokens_saved']:,} tokens "
                f"across {compaction['compaction_events']} events"
            )
        if recovery.get("total_errors", 0) > 0:
            bullets.append(
                f"4-layer recovery auto-resolved {recovery['auto_recovery_rate']*100:.0f}% of errors "
                f"({recovery['auto_recovered']}/{recovery['total_errors']})"
            )
        if tokens.get("total_tokens", 0) > 0:
            bullets.append(
                f"Token efficiency {tokens['efficiency']*100:.0f}% "
                f"({tokens['total_tokens']:,} total tokens)"
            )
        if quality.get("count", 0) > 0:
            bullets.append(
                f"LLM-as-Judge avg quality score {quality['mean']}/10 "
                f"(n={quality['count']})"
            )
        if users.get("total_users", 0) > 0:
            bullets.append(
                f"{users['total_users']} users, "
                f"{users['total_sessions']} sessions, "
                f"{users['total_analyses']} analyses"
            )
        return bullets

    # -- Task-level metrics (Phase 8 — Task Lifecycle) -----------------------

    async def task_dashboard(self, task_id: str) -> dict[str, Any]:
        """Aggregated metrics for a single autonomous task."""
        completion = await self._task_completion_rate(task_id)
        kpi_hit = await self._task_kpi_hit_rate(task_id)
        drift_recovery = await self._task_drift_recovery_rate(task_id)
        runtime = await self._task_unattended_days(task_id)
        return {
            "task_id": task_id,
            "auto_completion_rate": completion,
            "kpi_hit_rate": kpi_hit,
            "drift_recovery_rate": drift_recovery,
            "unattended_runtime_days": runtime,
        }

    async def _task_completion_rate(self, task_id: str) -> dict[str, Any]:
        """Fraction of cycles that completed successfully."""
        try:
            cursor = await self._conn.execute(
                "SELECT COUNT(*) FROM task_cycles WHERE task_id = ?", (task_id,))
            total = (await cursor.fetchone())[0]
            cursor = await self._conn.execute(
                "SELECT COUNT(*) FROM task_cycles WHERE task_id = ? AND status = 'success'",
                (task_id,))
            success = (await cursor.fetchone())[0]
            return {"total": total, "success": success,
                    "rate": success / total if total else 0.0}
        except Exception:
            return {"total": 0, "success": 0, "rate": 0.0}

    async def _task_kpi_hit_rate(self, task_id: str) -> dict[str, Any]:
        """Fraction of quality_score entries ≥ 7.0."""
        try:
            cursor = await self._conn.execute(
                "SELECT COUNT(*) FROM kpi_trajectory WHERE task_id = ? AND metric = 'quality_score'",
                (task_id,))
            total = (await cursor.fetchone())[0]
            cursor = await self._conn.execute(
                "SELECT COUNT(*) FROM kpi_trajectory WHERE task_id = ? AND metric = 'quality_score' AND value >= 7.0",
                (task_id,))
            hits = (await cursor.fetchone())[0]
            return {"total": total, "hits": hits,
                    "rate": hits / total if total else 0.0}
        except Exception:
            return {"total": 0, "hits": 0, "rate": 0.0}

    async def _task_drift_recovery_rate(self, task_id: str) -> dict[str, Any]:
        """Fraction of drift incidents that were resolved."""
        try:
            cursor = await self._conn.execute(
                "SELECT COUNT(*) FROM drift_incidents WHERE task_id = ?", (task_id,))
            total = (await cursor.fetchone())[0]
            cursor = await self._conn.execute(
                "SELECT COUNT(*) FROM drift_incidents WHERE task_id = ? AND resolved = 1",
                (task_id,))
            resolved = (await cursor.fetchone())[0]
            return {"total": total, "resolved": resolved,
                    "rate": resolved / total if total else 0.0}
        except Exception:
            return {"total": 0, "resolved": 0, "rate": 0.0}

    async def _task_unattended_days(self, task_id: str) -> float:
        """Days between first and last cycle for this task."""
        try:
            cursor = await self._conn.execute(
                "SELECT MIN(started_at), MAX(started_at) FROM task_cycles WHERE task_id = ?",
                (task_id,))
            row = await cursor.fetchone()
            if row and row[0] and row[1]:
                return (row[1] - row[0]) / 86400.0
        except Exception:
            pass
        return 0.0

    async def close(self) -> None:
        await self._conn.close()
