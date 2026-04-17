"""Drift Detector — detect long-term deviation from user goals.

Runs after each cycle to check whether the task is drifting from its
original specification.  Low/medium severity signals trigger automatic
correction; high severity escalates to the user.

Drift signals:
    - kpi_miss_streak   — consecutive KPI failures
    - quality_decay     — quality score trending downward
    - stale_watchlist   — ticker scope unchanged for too long
    - report_redundancy — recent reports too similar
    - data_freshness    — circuit breakers tripped / data stale

Usage::

    detector = DriftDetector()
    signals = await detector.check(spec, memory)
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from app.harness.task_spec import TaskSpec
from app.harness.task_memory import DriftIncident, TaskMemory

logger = logging.getLogger(__name__)


@dataclass
class DriftSignal:
    """A single detected drift signal."""
    signal: str
    severity: str       # low, medium, high
    detail: str
    suggested_action: str


class DriftDetector:
    """Detect long-term deviation from user goals."""

    def __init__(
        self,
        kpi_miss_streak_threshold: int = 3,
        quality_decay_threshold: float = 1.5,
        stale_cycles_threshold: int = 10,
        consecutive_fail_threshold: int = 5,
    ) -> None:
        self._kpi_miss_streak = kpi_miss_streak_threshold
        self._quality_decay = quality_decay_threshold
        self._stale_cycles = stale_cycles_threshold
        self._consec_fail = consecutive_fail_threshold

    async def check(
        self, spec: TaskSpec, memory: TaskMemory
    ) -> list[DriftSignal]:
        """Run all drift checks and return detected signals."""
        signals: list[DriftSignal] = []

        trajectory = await memory.get_kpi_trajectory(spec.task_id, limit=20)
        history = await memory.get_cycle_history(spec.task_id, limit=10)

        s = self._check_kpi_miss_streak(trajectory)
        if s:
            signals.append(s)

        s = self._check_quality_decay(trajectory)
        if s:
            signals.append(s)

        s = self._check_consecutive_failures(history)
        if s:
            signals.append(s)

        # Persist detected signals as incidents
        for sig in signals:
            incident = DriftIncident(
                id=uuid.uuid4().hex[:16],
                task_id=spec.task_id,
                detected_at=time.time(),
                signal=sig.signal,
                severity=sig.severity,
                action=sig.suggested_action,
            )
            await memory.save_drift_incident(incident)

        return signals

    def _check_kpi_miss_streak(
        self, trajectory: list[dict[str, Any]]
    ) -> DriftSignal | None:
        """Detect consecutive KPI misses."""
        quality_points = [
            p for p in trajectory if p["metric"] == "quality_score"
        ]
        if len(quality_points) < self._kpi_miss_streak:
            return None

        # Check most recent N points (trajectory is newest-first)
        recent = quality_points[: self._kpi_miss_streak]
        all_low = all(p["value"] < 7.0 for p in recent)
        if all_low:
            return DriftSignal(
                signal="kpi_miss_streak",
                severity="medium",
                detail=f"Quality score below 7.0 for {self._kpi_miss_streak} consecutive cycles",
                suggested_action="tighten_kpi_filters",
            )
        return None

    def _check_quality_decay(
        self, trajectory: list[dict[str, Any]]
    ) -> DriftSignal | None:
        """Detect quality score trending downward."""
        quality_points = [
            p["value"] for p in trajectory if p["metric"] == "quality_score"
        ]
        if len(quality_points) < 4:
            return None

        # Compare average of first half vs second half (newest first)
        mid = len(quality_points) // 2
        recent_avg = sum(quality_points[:mid]) / mid
        older_avg = sum(quality_points[mid:]) / (len(quality_points) - mid)

        decay = older_avg - recent_avg
        if decay >= self._quality_decay:
            return DriftSignal(
                signal="quality_decay",
                severity="medium",
                detail=f"Quality score dropped by {decay:.1f} (from {older_avg:.1f} to {recent_avg:.1f})",
                suggested_action="re_anchor_task_spec",
            )
        return None

    def _check_consecutive_failures(
        self, history: list[Any]
    ) -> DriftSignal | None:
        """Detect consecutive cycle failures."""
        if len(history) < self._consec_fail:
            return None

        recent = history[: self._consec_fail]
        if all(getattr(c, "status", "") == "failed" for c in recent):
            return DriftSignal(
                signal="consecutive_failures",
                severity="high",
                detail=f"{self._consec_fail} consecutive cycles failed",
                suggested_action="pause_and_escalate",
            )
        return None
