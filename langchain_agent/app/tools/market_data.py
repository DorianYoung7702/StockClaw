"""Tool for fetching real-time market overview and conditions."""

from __future__ import annotations

import json
import logging
import sys
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.config import get_settings

logger = logging.getLogger(__name__)


class MarketOverviewInput(BaseModel):
    market_type: Literal["us_stock", "hk_stock"] = Field(
        default="us_stock",
        description="Market to check: us_stock or hk_stock",
    )


def _get_market_conditions(market_type_str: str) -> dict:
    settings = get_settings()
    root = str(settings.monitor_module_root)
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        from config import Config as OBBConfig
        from config import MarketType as OBBMarketType
        from market_condition import MarketConditionChecker

        mt = OBBMarketType(market_type_str)
        cfg = OBBConfig()
        checker = MarketConditionChecker(cfg)
        conditions = checker.check_all_timeframes(mt)

        result: dict = {"market_type": market_type_str, "timeframes": {}}
        for tf, (is_bearish, etf_conds) in conditions.items():
            result["timeframes"][tf] = {
                "is_bearish": is_bearish,
                "etf_conditions": {k: v for k, v in etf_conds.items()},
            }

        should_alert = checker.should_trigger_alerts(mt)
        result["should_trigger_alerts"] = should_alert
        return result
    except Exception as exc:
        logger.warning("Failed to get market conditions: %s", exc)
        return {"error": str(exc)}


def _get_index_snapshot(market_type_str: str) -> dict:
    """Index quotes — reads from SQLite market_cache first, yfinance fallback."""
    import asyncio
    from app.providers import market_cache

    # --- Try SQLite cache (populated by daily refresh / startup) -----------
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    cached: dict | None = None
    if loop and loop.is_running():
        # We are inside an existing event loop (e.g. called from a LangChain
        # tool running on the async FastAPI thread).  Use a dedicated thread
        # to avoid "cannot run nested event loop" errors.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            cached = pool.submit(
                asyncio.run, market_cache.get_index_snapshot(market_type_str)
            ).result(timeout=5)
    else:
        cached = asyncio.run(market_cache.get_index_snapshot(market_type_str))

    if cached:
        logger.debug("index_snapshot:%s served from SQLite cache", market_type_str)
        return cached

    # --- Fallback: live yfinance fetch (throttled by Semaphore) ------------
    logger.info("index_snapshot:%s cache miss — falling back to yfinance", market_type_str)
    from app.providers.ticker_cache import get_yf_history

    symbols = {
        "us_stock": ["^GSPC", "^IXIC", "^DJI", "QQQ", "SPY"],
        "hk_stock": ["^HSI", "^HSCE"],
    }
    tickers = symbols.get(market_type_str, symbols["us_stock"])
    snapshot: dict = {}
    for sym in tickers:
        try:
            hist = get_yf_history(sym, period="2d")
            if hist.empty:
                continue
            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else latest
            snapshot[sym] = {
                "price": round(float(latest["Close"]), 2),
                "change_pct": round(
                    (float(latest["Close"]) - float(prev["Close"])) / float(prev["Close"]) * 100,
                    2,
                ),
            }
        except Exception:
            continue
    # Snapshot fallback when live fetches all fail
    if not snapshot:
        from app.providers.ticker_cache import _load_snapshot
        snap = _load_snapshot(f"index_snapshot_{market_type_str}")
        if snap:
            snapshot = snap
            logger.info("index_snapshot:%s using snapshot fallback", market_type_str)
    return snapshot


@tool("get_market_overview", args_schema=MarketOverviewInput)
def get_market_overview(market_type: str = "us_stock") -> str:
    """Get current market conditions and major index snapshots.

    Returns market bearish/bullish assessment from ETF patterns,
    plus latest index prices and daily change percentages.
    """
    conditions = _get_market_conditions(market_type)
    snapshot = _get_index_snapshot(market_type)
    result = {**conditions, "index_snapshot": snapshot}
    return json.dumps(result, default=str, ensure_ascii=False)
