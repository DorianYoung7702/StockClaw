"""Tool for fetching upcoming catalysts (earnings dates, events, analyst estimates).

Data sources (priority order):
  1. FMP — earnings calendar, analyst estimates, price targets
  2. yfinance — calendar, earnings timestamps, ex-dividend
"""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CatalystsInput(BaseModel):
    symbol: str = Field(description="Ticker symbol, e.g. AAPL")


# ---------------------------------------------------------------------------
# FMP catalyst data
# ---------------------------------------------------------------------------

def _fetch_fmp_catalysts(symbol: str) -> dict:
    """Fetch earnings calendar + analyst estimates + price targets from FMP."""
    from app.config import get_settings

    settings = get_settings()
    if not settings.fmp_api_key:
        return {}

    from app.harness.circuit_breaker import get_breaker

    breaker = get_breaker("fmp")
    if not breaker.allow_request():
        return {}

    import httpx

    base = "https://financialmodelingprep.com/api/v3"
    params = {"apikey": settings.fmp_api_key}
    out: dict = {}

    try:
        with httpx.Client(timeout=15.0) as client:
            # Earnings calendar
            resp = client.get(f"{base}/earning_calendar", params={**params, "symbol": symbol})
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    out["next_earnings"] = data[0].get("date", "")
                    out["eps_estimated"] = data[0].get("epsEstimated")
                    out["revenue_estimated"] = data[0].get("revenueEstimated")

            # Analyst estimates (consensus)
            resp = client.get(f"{base}/analyst-estimates/{symbol}", params={**params, "limit": 1})
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    est = data[0]
                    out["analyst_estimates"] = {
                        "date": est.get("date", ""),
                        "revenue_avg": est.get("estimatedRevenueAvg"),
                        "revenue_low": est.get("estimatedRevenueLow"),
                        "revenue_high": est.get("estimatedRevenueHigh"),
                        "ebitda_avg": est.get("estimatedEbitdaAvg"),
                        "net_income_avg": est.get("estimatedNetIncomeAvg"),
                        "eps_avg": est.get("estimatedEpsAvg"),
                        "eps_low": est.get("estimatedEpsLow"),
                        "eps_high": est.get("estimatedEpsHigh"),
                    }

            # Price target consensus
            resp = client.get(f"{base}/price-target-consensus/{symbol}", params=params)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    pt = data[0]
                    out["price_target"] = {
                        "target_high": pt.get("targetHigh"),
                        "target_low": pt.get("targetLow"),
                        "target_consensus": pt.get("targetConsensus"),
                        "target_median": pt.get("targetMedian"),
                    }

        breaker.record_success()
    except Exception as exc:
        breaker.record_failure()
        logger.debug("FMP catalysts failed for %s: %s", symbol, exc)

    return out


# ---------------------------------------------------------------------------
# yfinance catalyst data
# ---------------------------------------------------------------------------

def _fetch_yf_catalysts(symbol: str) -> dict:
    """Fetch catalysts from yfinance (calendar + info)."""
    from app.providers.ticker_cache import get_yf_calendar, get_yf_info

    out: dict = {"events": []}

    try:
        cal = get_yf_calendar(symbol)
        if cal is not None:
            cal_data = cal if isinstance(cal, dict) else cal.to_dict()
            for key, value in cal_data.items():
                if isinstance(value, dict):
                    for sub_key, sub_val in value.items():
                        out["events"].append({
                            "type": str(key),
                            "label": str(sub_key),
                            "value": sub_val.isoformat() if hasattr(sub_val, "isoformat") else str(sub_val),
                        })
                else:
                    out["events"].append({
                        "type": "calendar",
                        "label": str(key),
                        "value": value.isoformat() if hasattr(value, "isoformat") else str(value),
                    })
    except Exception as exc:
        logger.debug("Calendar fetch failed for %s: %s", symbol, exc)

    try:
        info = get_yf_info(symbol)

        if info.get("earningsTimestamp"):
            from datetime import datetime, timezone
            out.setdefault("next_earnings", datetime.fromtimestamp(
                info["earningsTimestamp"], tz=timezone.utc
            ).isoformat())

        ex_div = info.get("exDividendDate")
        if ex_div:
            from datetime import datetime, timezone
            if isinstance(ex_div, (int, float)):
                out["ex_dividend_date"] = datetime.fromtimestamp(ex_div, tz=timezone.utc).isoformat()
            else:
                out["ex_dividend_date"] = str(ex_div)
    except Exception as exc:
        logger.debug("yfinance info failed for %s: %s", symbol, exc)

    return out


@tool("get_catalysts", args_schema=CatalystsInput)
def get_catalysts(symbol: str) -> str:
    """Fetch upcoming catalysts for a stock: next earnings date, ex-dividend
    date, analyst estimates, price target consensus, and scheduled events.

    Uses FMP (if configured) for analyst estimates and price targets,
    with yfinance fallback for calendar data.
    """
    data: dict = {"symbol": symbol}

    # FMP first — richer data (estimates, price targets)
    fmp_data = _fetch_fmp_catalysts(symbol)
    if fmp_data:
        data.update(fmp_data)

    # yfinance supplement
    yf_data = _fetch_yf_catalysts(symbol)
    for k, v in yf_data.items():
        if k not in data or not data[k]:
            data[k] = v

    if len(data) <= 1:
        data["error"] = f"No catalyst data found for {symbol}"

    return json.dumps(data, default=str, ensure_ascii=False)
