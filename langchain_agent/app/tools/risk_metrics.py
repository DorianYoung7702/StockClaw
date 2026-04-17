"""Tool for fetching risk-related metrics for a stock."""

from __future__ import annotations

import json
import logging
from typing import Optional

import numpy as np
from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RiskMetricsInput(BaseModel):
    symbol: str = Field(description="Ticker symbol, e.g. AAPL")


def _safe(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _compute_volatility(symbol: str) -> Optional[float]:
    """Annualised volatility from 1-year daily returns."""
    from app.providers.ticker_cache import get_yf_history

    try:
        hist = get_yf_history(symbol, period="1y")
        if hist.empty or len(hist) < 20:
            return None
        returns = hist["Close"].pct_change().dropna()
        return float(np.std(returns) * np.sqrt(252))
    except Exception:
        return None


@tool("get_risk_metrics", args_schema=RiskMetricsInput)
def get_risk_metrics(symbol: str) -> str:
    """Fetch risk-related metrics for a stock including beta, volatility,
    short interest ratio, and basic insider transaction signals.

    Returns a JSON object with risk indicators useful for assessing downside
    exposure and market sentiment towards the stock.
    """
    from app.providers.ticker_cache import get_yf_info, get_yf_insider_transactions

    data: dict = {"symbol": symbol}

    try:
        info = get_yf_info(symbol)

        data["beta"] = _safe(info.get("beta"))
        data["short_ratio"] = _safe(info.get("shortRatio"))
        data["short_percent_of_float"] = _safe(info.get("shortPercentOfFloat"))
        data["fifty_two_week_high"] = _safe(info.get("fiftyTwoWeekHigh"))
        data["fifty_two_week_low"] = _safe(info.get("fiftyTwoWeekLow"))
        data["current_price"] = _safe(
            info.get("currentPrice") or info.get("regularMarketPrice")
        )

        if data["fifty_two_week_high"] and data["current_price"]:
            data["pct_from_52w_high"] = round(
                (data["current_price"] - data["fifty_two_week_high"])
                / data["fifty_two_week_high"]
                * 100,
                2,
            )

        data["annualised_volatility"] = _compute_volatility(symbol)

        try:
            insider = get_yf_insider_transactions(symbol)
            if insider is not None and not insider.empty:
                recent = insider.head(5).to_dict(orient="records")
                for r in recent:
                    for k, v in list(r.items()):
                        if hasattr(v, "isoformat"):
                            r[k] = v.isoformat()
                data["recent_insider_transactions"] = recent
            else:
                data["recent_insider_transactions"] = []
        except Exception:
            data["recent_insider_transactions"] = []

    except Exception as exc:
        logger.warning("Risk metrics fetch failed for %s: %s", symbol, exc)
        data["error"] = str(exc)

    return json.dumps(data, default=str, ensure_ascii=False)
