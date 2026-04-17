"""APScheduler-driven daily monitor-pool refresh.

Replaces the legacy ``monitor/crontab`` for Docker deployments where the
FastAPI container has no access to host cron.

One ``AsyncIOScheduler`` lives inside the FastAPI event loop with three
cron jobs (US stocks / ETFs / HK stocks). Each job offloads the blocking
``build_monitor_pool`` via ``asyncio.to_thread``.

Config (all optional, read from ``Settings``):

- ``POOL_REFRESH_ENABLED`` (default True)
- ``POOL_REFRESH_TIMEZONE`` (default ``Asia/Shanghai``)
- ``POOL_REFRESH_US_CRON``  (default ``0 4 * * *``)
- ``POOL_REFRESH_ETF_CRON`` (default ``15 4 * * *``)
- ``POOL_REFRESH_HK_CRON``  (default ``30 17 * * 1-5``)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PoolRefreshScheduler:
    """Schedule daily rebuilds of monitor cache JSON files."""

    def __init__(
        self,
        *,
        timezone: str = "Asia/Shanghai",
        us_cron: str = "0 4 * * *",
        etf_cron: str = "15 4 * * *",
        hk_cron: str = "30 17 * * 1-5",
    ) -> None:
        self._timezone = timezone
        self._us_cron = us_cron
        self._etf_cron = etf_cron
        self._hk_cron = hk_cron
        self._scheduler: Optional[Any] = None

    async def start(self) -> None:
        """Install cron jobs and start the scheduler. Idempotent."""
        if self._scheduler is not None:
            return
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            logger.warning(
                "PoolRefreshScheduler: apscheduler not installed — "
                "daily pool refresh disabled."
            )
            return

        self._scheduler = AsyncIOScheduler(timezone=self._timezone)

        job_specs = [
            ("us_stock", self._us_cron, "pool_refresh_us_stock"),
            ("etf", self._etf_cron, "pool_refresh_etf"),
            ("hk_stock", self._hk_cron, "pool_refresh_hk_stock"),
        ]
        for market_type, cron_expr, job_id in job_specs:
            try:
                trigger = CronTrigger.from_crontab(cron_expr, timezone=self._timezone)
            except Exception as exc:
                logger.warning(
                    "PoolRefreshScheduler: invalid cron '%s' for %s — skipping (%s)",
                    cron_expr, market_type, exc,
                )
                continue
            self._scheduler.add_job(
                _refresh_pool,
                trigger=trigger,
                args=[market_type],
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=3600,
            )

        self._scheduler.start()
        logger.info(
            "PoolRefreshScheduler started (tz=%s): us='%s', etf='%s', hk='%s'",
            self._timezone, self._us_cron, self._etf_cron, self._hk_cron,
        )

    async def stop(self) -> None:
        """Shutdown. Safe to call multiple times."""
        if self._scheduler is None:
            return
        try:
            self._scheduler.shutdown(wait=False)
        except Exception as exc:
            logger.warning("PoolRefreshScheduler shutdown error: %s", exc)
        self._scheduler = None
        logger.info("PoolRefreshScheduler stopped")

    def list_jobs(self) -> list[dict[str, Any]]:
        """Return next-run info for dashboards."""
        if self._scheduler is None:
            return []
        out: list[dict[str, Any]] = []
        for job in self._scheduler.get_jobs():
            out.append({
                "id": job.id,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            })
        return out

    async def trigger_now(self, market_type: str) -> dict[str, Any]:
        """Manually kick off a refresh (bypasses schedule)."""
        logger.info("PoolRefreshScheduler: manual trigger for %s", market_type)
        await _refresh_pool(market_type)
        return {"market_type": market_type, "status": "triggered"}


async def _refresh_pool(market_type: str) -> None:
    """Run a single pool rebuild in a worker thread."""
    from app.providers.monitor_pool_builder import build_monitor_pool

    logger.info("PoolRefresh: starting %s rebuild", market_type)
    try:
        result = await asyncio.to_thread(build_monitor_pool, market_type)
        logger.info("PoolRefresh: %s done — %s", market_type, result)
    except Exception as exc:
        logger.error("PoolRefresh: %s failed — %s", market_type, exc, exc_info=True)
