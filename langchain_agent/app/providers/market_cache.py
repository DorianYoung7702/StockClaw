"""SQLite-persisted daily market cache.

Stores index snapshots and strong-stock screening results so that
high-frequency reads never hit yfinance directly.  Data is refreshed
on application startup and via an admin API endpoint.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from app.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

_DB_PATH = str(PROJECT_ROOT / "atlas_market_cache.db")
_STALE_HOURS = 24  # data older than this is considered expired

# Global Semaphore shared with ticker_cache to throttle yfinance requests
_yf_semaphore = threading.Semaphore(2)


def get_yf_semaphore() -> threading.Semaphore:
    """Return the module-level yfinance concurrency limiter."""
    return _yf_semaphore


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

async def _ensure_table(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS market_cache (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    await db.commit()


async def _get(key: str) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(_DB_PATH) as db:
        await _ensure_table(db)
        cursor = await db.execute(
            "SELECT value, updated_at FROM market_cache WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        value_str, updated_at_str = row
        try:
            updated = datetime.fromisoformat(updated_at_str)
        except (ValueError, TypeError):
            return None
        age_hours = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
        if age_hours > _STALE_HOURS:
            logger.debug("market_cache key=%s is stale (%.1fh old)", key, age_hours)
            return None
        return json.loads(value_str)


async def _set(key: str, value: Any) -> None:
    now = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(value, default=str, ensure_ascii=False)
    async with aiosqlite.connect(_DB_PATH) as db:
        await _ensure_table(db)
        await db.execute(
            """
            INSERT INTO market_cache (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                           updated_at = excluded.updated_at
            """,
            (key, payload, now),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------

async def get_index_snapshot(market_type: str) -> Optional[dict[str, Any]]:
    """Read cached index snapshot.  Returns *None* on miss / stale."""
    return await _get(f"index_snapshot:{market_type}")


async def get_strong_stocks(market_type: str) -> Optional[list[dict[str, Any]]]:
    """Read cached strong-stock screening result.  Returns *None* on miss."""
    return await _get(f"strong_stocks:{market_type}")


# ---------------------------------------------------------------------------
# Refresh logic (writes)
# ---------------------------------------------------------------------------

async def refresh_index_snapshots() -> dict[str, Any]:
    """Fetch latest index quotes from yfinance and persist to SQLite.

    Uses the global Semaphore to throttle concurrent yfinance requests.
    Returns a dict of market_type -> snapshot or error message.
    """
    import asyncio
    from app.providers.ticker_cache import get_yf_history

    symbols_map: dict[str, list[str]] = {
        "us_stock": ["^GSPC", "^IXIC", "^DJI", "QQQ", "SPY"],
        "hk_stock": ["^HSI", "^HSCE"],
    }

    results: dict[str, Any] = {}
    for market_type, tickers in symbols_map.items():
        snapshot: dict[str, Any] = {}
        consecutive_failures = 0
        for sym in tickers:
            try:
                hist = await asyncio.to_thread(
                    _semaphored_history, sym, "2d"
                )
                if hist is None or hist.empty:
                    consecutive_failures += 1
                else:
                    latest = hist.iloc[-1]
                    prev = hist.iloc[-2] if len(hist) > 1 else latest
                    snapshot[sym] = {
                        "price": round(float(latest["Close"]), 2),
                        "change_pct": round(
                            (float(latest["Close"]) - float(prev["Close"]))
                            / float(prev["Close"])
                            * 100,
                            2,
                        ),
                    }
                    consecutive_failures = 0
            except Exception as exc:
                logger.warning("refresh_index_snapshots %s failed: %s", sym, exc)
                consecutive_failures += 1
            # Abort early if rate-limited (2+ consecutive failures)
            if consecutive_failures >= 2:
                logger.warning(
                    "refresh_index_snapshots: aborting %s after %d consecutive failures (likely rate-limited)",
                    market_type, consecutive_failures,
                )
                break
            # Small delay between symbols to avoid burst
            await asyncio.sleep(0.5)
        await _set(f"index_snapshot:{market_type}", snapshot)
        results[market_type] = snapshot
        logger.info(
            "market_cache: refreshed index_snapshot:%s  (%d symbols)",
            market_type,
            len(snapshot),
        )
    return results


def _semaphored_history(symbol: str, period: str):
    """Fetch yf history — semaphore is already acquired inside get_yf_history."""
    from app.providers.ticker_cache import get_yf_history

    return get_yf_history(symbol, period)


async def refresh_strong_stocks() -> dict[str, Any]:
    """Run strong-stock screening and persist results to SQLite.

    If the monitor/ JSON cache is missing, rebuild it first via
    ``monitor_pool_builder`` so that ``load_strong_stocks_with_params``
    has data to read.
    """
    import asyncio
    from app.providers.monitor_pool_builder import monitor_cache_exists, build_monitor_pool
    from app.tools.strong_stocks import load_strong_stocks_with_params

    results: dict[str, Any] = {}
    for market_type in ("us_stock", "hk_stock"):
        try:
            # Ensure monitor JSON cache exists before reading
            if not monitor_cache_exists(market_type):
                logger.info("refresh_strong_stocks: monitor cache missing for %s, building...", market_type)
                await asyncio.to_thread(build_monitor_pool, market_type)

            stocks = await asyncio.to_thread(
                load_strong_stocks_with_params, market_type
            )
            await _set(f"strong_stocks:{market_type}", stocks)
            count = len(stocks.get("stocks", [])) if isinstance(stocks, dict) else len(stocks)
            results[market_type] = f"ok ({count} stocks)"
            logger.info(
                "market_cache: refreshed strong_stocks:%s  (%d items)",
                market_type,
                count,
            )
        except Exception as exc:
            logger.warning("refresh_strong_stocks %s failed: %s", market_type, exc)
            results[market_type] = f"error: {exc}"
    return results


async def refresh_all() -> dict[str, Any]:
    """Full refresh: index snapshots + strong stocks."""
    idx = await refresh_index_snapshots()
    ss = await refresh_strong_stocks()
    return {"index_snapshots": idx, "strong_stocks": ss}
