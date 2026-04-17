"""Tools for managing the user's watchlist (query, add, remove)."""

from __future__ import annotations

import asyncio
import json
import logging
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.context import current_user_id

logger = logging.getLogger(__name__)


class WatchlistAddInput(BaseModel):
    ticker: str = Field(description="Ticker symbol to add, e.g. AAPL, 0700.HK, NKE")
    note: str = Field(default="", description="Optional note for this ticker")


class WatchlistRemoveInput(BaseModel):
    ticker: str = Field(description="Ticker symbol to remove, e.g. AAPL")


def _run_async(coro):
    """Run an async function from a sync context (LangChain tool)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=10)
    return asyncio.run(coro)


@tool("add_to_watchlist", args_schema=WatchlistAddInput)
def add_to_watchlist(ticker: str, note: str = "") -> str:
    """Add a stock ticker to the user's watchlist / observation list.

    IMPORTANT: You MUST call resolve_symbol first to get the validated ticker,
    then pass the resolved ticker to this tool. Do NOT pass raw user input directly.
    """
    from app.memory.watchlist import add_ticker

    try:
        uid = current_user_id.get()
        result = _run_async(add_ticker(uid, ticker.upper().strip(), note))
        return json.dumps({
            "status": "ok",
            "message": f"✅ **{result['ticker']}** 已加入观察组",
            "ticker": result["ticker"],
        }, ensure_ascii=False)
    except Exception as exc:
        logger.warning("add_to_watchlist failed for %s: %s", ticker, exc)
        return json.dumps({"status": "error", "error": str(exc)})


@tool("remove_from_watchlist", args_schema=WatchlistRemoveInput)
def remove_from_watchlist(ticker: str) -> str:
    """Remove a stock ticker from the user's watchlist.

    Use this when the user asks to remove / delete a stock from their watchlist.
    """
    from app.memory.watchlist import remove_ticker

    try:
        uid = current_user_id.get()
        removed = _run_async(remove_ticker(uid, ticker.upper().strip()))
        if removed:
            return json.dumps({"status": "ok", "message": f"{ticker.upper()} \u5df2\u4ece\u89c2\u5bdf\u7ec4\u79fb\u9664"}, ensure_ascii=False)
        return json.dumps({"status": "ok", "message": f"{ticker.upper()} \u4e0d\u5728\u89c2\u5bdf\u7ec4\u4e2d"}, ensure_ascii=False)
    except Exception as exc:
        logger.warning("remove_from_watchlist failed for %s: %s", ticker, exc)
        return json.dumps({"status": "error", "error": str(exc)})


@tool("clear_watchlist")
def clear_watchlist() -> str:
    """Clear all tickers from the user's watchlist.

    Use this when the user asks to empty / clear their entire watchlist.
    """
    from app.memory.watchlist import clear_all

    try:
        uid = current_user_id.get()
        count = _run_async(clear_all(uid))
        return json.dumps({"status": "ok", "message": f"已清空观察组（移除 {count} 只）"}, ensure_ascii=False)
    except Exception as exc:
        logger.warning("clear_watchlist failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


@tool("get_watchlist")
def get_watchlist() -> str:
    """Get the user's current watchlist (observed stocks).

    Returns a JSON array of watchlist entries, each with ticker, note, and
    the date it was added. Useful for checking which stocks the user is tracking.
    """
    from app.memory.watchlist import list_tickers

    try:
        uid = current_user_id.get()
        items = _run_async(list_tickers(uid))
        if not items:
            return json.dumps({"message": "观察组为空，尚未添加任何股票。", "tickers": []})
        return json.dumps(
            {"count": len(items), "tickers": items},
            default=str,
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.warning("get_watchlist failed: %s", exc)
        return json.dumps({"error": f"Failed to retrieve watchlist: {exc}"})
