"""Tool for fetching historical price / K-line data."""

from __future__ import annotations

import json
import logging
from typing import Literal, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PriceHistoryInput(BaseModel):
    symbol: str = Field(description="Ticker symbol, e.g. AAPL, TSLA, 0700.HK")
    period: Literal["1mo", "3mo", "6mo", "1y", "2y", "5y"] = Field(
        default="6mo",
        description="Historical period: 1mo, 3mo, 6mo, 1y, 2y, or 5y",
    )
    interval: Literal["1d", "1wk", "1mo"] = Field(
        default="1d",
        description="Data interval: 1d (daily), 1wk (weekly), or 1mo (monthly)",
    )


def _safe_float(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else round(f, 4)
    except (TypeError, ValueError):
        return None


@tool("get_price_history", args_schema=PriceHistoryInput)
def get_price_history(
    symbol: str,
    period: str = "6mo",
    interval: str = "1d",
) -> str:
    """Fetch historical OHLCV (Open/High/Low/Close/Volume) price data for a stock.

    Returns a JSON object with metadata and an array of candle records ordered
    from oldest to newest. Useful for trend analysis, moving averages, support/
    resistance levels, and general price movement review.
    """
    from app.providers.ticker_cache import get_yf_history

    try:
        df = get_yf_history(symbol, period=period, interval=interval)
        if df is None or df.empty:
            return json.dumps({"error": f"No price history found for {symbol}"})

        records = []
        for idx, row in df.iterrows():
            date_str = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
            records.append({
                "date": date_str,
                "open": _safe_float(row.get("Open")),
                "high": _safe_float(row.get("High")),
                "low": _safe_float(row.get("Low")),
                "close": _safe_float(row.get("Close")),
                "volume": int(row.get("Volume", 0)) if row.get("Volume") is not None else None,
            })

        # Summary stats
        closes = [r["close"] for r in records if r["close"] is not None]
        summary = {}
        if closes:
            summary = {
                "latest_close": closes[-1],
                "period_high": max(closes),
                "period_low": min(closes),
                "period_return_pct": round((closes[-1] - closes[0]) / closes[0] * 100, 2) if closes[0] else None,
                "data_points": len(records),
            }

        return json.dumps(
            {
                "symbol": symbol,
                "period": period,
                "interval": interval,
                "summary": summary,
                "candles": records,
            },
            default=str,
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.warning("get_price_history failed for %s: %s", symbol, exc)
        return json.dumps({"error": f"Failed to fetch price history for {symbol}: {exc}"})
