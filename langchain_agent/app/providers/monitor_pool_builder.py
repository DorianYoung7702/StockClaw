"""Bridge to build monitor/ cache pools from the backend.

Calls seed_and_build.build_pool (in the monitor/ module) which downloads
6-month price histories from yfinance and writes JSON cache files to
monitor/cache/.  This is the same logic the standalone seed_and_build.py
uses, but callable as a Python function from the backend.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


def _ensure_monitor_path() -> None:
    import sys
    root = str(get_settings().monitor_module_root)
    if root not in sys.path:
        sys.path.insert(0, root)


def monitor_cache_exists(market_type: str = "us_stock") -> bool:
    """Check if the monitor JSON cache file exists and is non-empty."""
    settings = get_settings()
    cache_dir = settings.monitor_module_root / "cache"
    cache_file = cache_dir / f"monitoring_pool_data_{market_type}.json"
    return cache_file.exists() and cache_file.stat().st_size > 100


def build_monitor_pool(market_type: str = "us_stock", top_n: int = 0) -> dict[str, Any]:
    """Build the monitoring pool for *market_type* and write to monitor/cache/.

    Returns a summary dict.  This is a **blocking, long-running** function
    (~2-10 min depending on symbol count and yfinance rate limits).
    Run it in a background thread.
    """
    _ensure_monitor_path()

    import os
    # Run inside the monitor directory so relative CSV paths resolve correctly
    original_cwd = os.getcwd()
    monitor_root = str(get_settings().monitor_module_root)

    try:
        os.chdir(monitor_root)

        from seed_and_build import build_pool, seed_us_csv, seed_hk_csv, seed_etf_csv

        # Ensure CSV seed files exist
        seed_map = {
            "us_stock": seed_us_csv,
            "hk_stock": seed_hk_csv,
            "etf": seed_etf_csv,
        }
        seed_fn = seed_map.get(market_type)
        if seed_fn:
            seed_fn()  # no-op if file already exists

        logger.info("monitor_pool_builder: building %s (top_n=%d)...", market_type, top_n)
        build_pool(market_type, top_n=top_n)

        cache_file = Path("cache") / f"monitoring_pool_data_{market_type}.json"
        if cache_file.exists():
            import json
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            count = data.get("symbol_count", 0)
            logger.info("monitor_pool_builder: %s complete — %d symbols cached", market_type, count)
            return {"market_type": market_type, "symbol_count": count, "status": "ok"}
        else:
            logger.warning("monitor_pool_builder: %s — cache file not created", market_type)
            return {"market_type": market_type, "symbol_count": 0, "status": "no_data"}

    except Exception as exc:
        logger.error("monitor_pool_builder: %s failed: %s", market_type, exc, exc_info=True)
        return {"market_type": market_type, "symbol_count": 0, "status": f"error: {exc}"}
    finally:
        os.chdir(original_cwd)


def build_all_pools(top_n: int = 0) -> dict[str, Any]:
    """Build pools for all market types sequentially."""
    results = {}
    for mt in ("us_stock", "hk_stock"):
        results[mt] = build_monitor_pool(mt, top_n=top_n)
    return results
