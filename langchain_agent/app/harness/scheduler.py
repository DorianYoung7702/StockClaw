"""Task Scheduler — drive unattended recurring execution.

Phase 2 module: provides APScheduler integration for cron-based and
event-triggered task execution.  Phase 1 uses manual triggering only
(``POST /tasks/{id}/run``).

Usage::

    scheduler = TaskScheduler()
    await scheduler.start()       # in FastAPI lifespan
    await scheduler.schedule_task(spec)
    await scheduler.force_run(task_id, user_id)
    await scheduler.stop()        # in FastAPI lifespan shutdown
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.harness.task_spec import TaskSpec, TaskSpecStore
from app.harness.task_memory import TaskMemory
from app.harness.cycle_runtime import CycleRuntime

logger = logging.getLogger(__name__)


class TaskScheduler:
    """Manages recurring task execution.

    Phase 1: manual-only (``force_run``).
    Phase 2: APScheduler integration with cron triggers.
    """

    def __init__(self, cycle_timeout: int = 300) -> None:
        self._runtime = CycleRuntime(timeout_seconds=cycle_timeout)
        self._running = False
        # Phase 2: self._scheduler = AsyncScheduler(...)

    async def start(self) -> None:
        """Called during FastAPI lifespan startup.

        Phase 1: no-op (manual triggering only).
        Phase 2: start APScheduler and rebuild schedules from DB.
        """
        self._running = True
        logger.info("TaskScheduler started (manual-trigger mode)")
        # Phase 2:
        # store = await TaskSpecStore.create()
        # active = await store.list_tasks_all_users(status="active")
        # for spec in active:
        #     await self.schedule_task(spec)
        # await store.close()

    async def stop(self) -> None:
        """Called during FastAPI lifespan shutdown."""
        self._running = False
        logger.info("TaskScheduler stopped")
        # Phase 2: await self._scheduler.shutdown()

    async def schedule_task(self, spec: TaskSpec) -> None:
        """Register a task's cadence with the scheduler.

        Phase 1: no-op — tasks run via ``force_run`` only.
        Phase 2: parse spec.cadence as cron trigger → add job.
        """
        logger.info("Task %s registered (cadence=%s) [manual-only in Phase 1]",
                     spec.task_id, spec.cadence)
        # Phase 2:
        # trigger = CronTrigger.from_crontab(spec.cadence)
        # self._scheduler.add_job(
        #     self._execute_cycle, trigger,
        #     args=[spec.task_id, spec.user_id],
        #     id=spec.task_id,
        #     replace_existing=True,
        # )

    async def unschedule_task(self, task_id: str) -> None:
        """Remove a task from the schedule."""
        logger.info("Task %s unscheduled", task_id)
        # Phase 2: self._scheduler.remove_job(task_id)

    async def force_run(self, task_id: str, user_id: str) -> dict[str, Any]:
        """Manually trigger a single cycle for a task.

        This is the primary execution path in Phase 1.

        Returns
        -------
        dict
            Cycle result summary (cycle_id, status, quality_score, errors).
        """
        store = await TaskSpecStore.create()
        spec = await store.get_task(user_id, task_id)
        await store.close()

        if not spec:
            return {"error": f"Task {task_id} not found for user {user_id}"}

        if spec.status != "active":
            return {"error": f"Task {task_id} is {spec.status}, not active"}

        # Check stop conditions
        mem = await TaskMemory.create()
        cycle_count = await mem.get_completed_cycle_count(task_id)
        max_cycles = spec.stop_conditions.get("max_cycles", 999)
        if cycle_count >= max_cycles:
            await mem.close()
            # Auto-complete the task
            store2 = await TaskSpecStore.create()
            await store2.update_task(user_id, task_id, status="completed")
            await store2.close()
            return {"error": f"Task {task_id} reached max_cycles ({max_cycles})"}

        # Get previous summary for context injection
        prev_summary = await mem.get_latest_summary(task_id)
        previous_cycles = await mem.get_cycle_history(task_id, limit=1)
        previous_cycle = previous_cycles[0] if previous_cycles else None
        drift_incidents = await mem.get_drift_incidents(task_id, unresolved_only=False, limit=5)
        await mem.close()

        # Execute cycle
        result = await self._runtime.run_cycle(
            spec,
            prev_summary=prev_summary,
            previous_cycle=previous_cycle,
            recent_drifts=[
                {
                    "signal": incident.signal,
                    "severity": incident.severity,
                    "action": incident.action,
                }
                for incident in drift_incidents
            ],
        )

        # Run drift detection (Phase 3)
        await self._run_drift_check(spec)

        return {
            "cycle_id": result.cycle_id,
            "task_id": result.task_id,
            "status": result.status,
            "quality_score": result.quality_score,
            "errors": result.errors,
            "kpi_check": result.kpi_check,
        }

    async def _run_drift_check(self, spec: TaskSpec) -> None:
        """Run drift detection after a cycle (Phase 3)."""
        try:
            from app.harness.drift_detector import DriftDetector

            detector = DriftDetector()
            mem = await TaskMemory.create()
            signals = await detector.check(spec, mem)
            await mem.close()

            for sig in signals:
                logger.warning(
                    "Drift detected for task %s: %s (%s) — %s",
                    spec.task_id, sig.signal, sig.severity, sig.detail,
                )
                # Phase 3: implement auto-correction actions
                if sig.severity == "high" and sig.suggested_action == "pause_and_escalate":
                    store = await TaskSpecStore.create()
                    await store.update_task(spec.user_id, spec.task_id, status="paused")
                    await store.close()
                    logger.warning("Task %s auto-paused due to %s", spec.task_id, sig.signal)
        except Exception as exc:
            logger.error("Drift check failed for task %s: %s", spec.task_id, exc)
