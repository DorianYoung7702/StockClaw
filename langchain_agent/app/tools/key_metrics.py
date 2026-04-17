"""Tool for fetching key financial metrics and valuation ratios."""

from __future__ import annotations

import json
import logging
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

try:
    import openbb as _obb_check  # noqa: F401
    _OPENBB_AVAILABLE = True
except Exception:
    _OPENBB_AVAILABLE = False
    logger.info("OpenBB not available — key_metrics will use yfinance only")


class KeyMetricsInput(BaseModel):
    symbol: str = Field(description="Ticker symbol, e.g. AAPL, MSFT")


def _safe(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else f  # NaN -> None
    except (TypeError, ValueError):
        return None


def _fetch_metrics_openbb(symbol: str) -> dict:
    if not _OPENBB_AVAILABLE:
        return {}
    out: dict = {}
    try:
        from openbb import obb

        try:
            metrics = obb.equity.fundamental.metrics(symbol=symbol, provider="yfinance")
            df = metrics.to_dataframe()
            if not df.empty:
                row = df.iloc[0].to_dict()
                out.update(row)
        except Exception as exc:
            logger.debug("OpenBB metrics failed for %s: %s", symbol, exc)

        try:
            ratios = obb.equity.fundamental.ratios(symbol=symbol, provider="yfinance")
            df = ratios.to_dataframe()
            if not df.empty:
                row = df.iloc[0].to_dict()
                out.update(row)
        except Exception as exc:
            logger.debug("OpenBB ratios failed for %s: %s", symbol, exc)
    except Exception as exc:
        logger.debug("OpenBB import/init failed for %s: %s", symbol, exc)

    return out


def _fetch_metrics_yfinance(symbol: str) -> dict:
    from app.providers.ticker_cache import get_yf_info

    try:
        info = get_yf_info(symbol)
        return {
            "pe_ratio": _safe(info.get("trailingPE")),
            "forward_pe": _safe(info.get("forwardPE")),
            "pb_ratio": _safe(info.get("priceToBook")),
            "ps_ratio": _safe(info.get("priceToSalesTrailing12Months")),
            "peg_ratio": _safe(info.get("pegRatio")),
            "ev_to_ebitda": _safe(info.get("enterpriseToEbitda")),
            "dividend_yield": _safe(info.get("dividendYield")),
            "roe": _safe(info.get("returnOnEquity")),
            "roa": _safe(info.get("returnOnAssets")),
            "debt_to_equity": _safe(info.get("debtToEquity")),
            "current_ratio": _safe(info.get("currentRatio")),
            "quick_ratio": _safe(info.get("quickRatio")),
            "gross_margin": _safe(info.get("grossMargins")),
            "operating_margin": _safe(info.get("operatingMargins")),
            "net_margin": _safe(info.get("profitMargins")),
            "revenue_growth_yoy": _safe(info.get("revenueGrowth")),
            "earnings_growth_yoy": _safe(info.get("earningsGrowth")),
            "beta": _safe(info.get("beta")),
            "fifty_two_week_high": _safe(info.get("fiftyTwoWeekHigh")),
            "fifty_two_week_low": _safe(info.get("fiftyTwoWeekLow")),
            "market_cap": _safe(info.get("marketCap")),
            "current_price": _safe(info.get("currentPrice") or info.get("regularMarketPrice")),
        }
    except Exception as exc:
        logger.warning("yfinance info failed for %s: %s", symbol, exc)
        return {}


def _sanitise(data: dict) -> dict:
    clean: dict = {}
    for k, v in data.items():
        if hasattr(v, "isoformat"):
            clean[k] = v.isoformat()
        elif isinstance(v, float) and v != v:
            clean[k] = None
        else:
            clean[k] = v
    return clean


def _fetch_metrics_configured_provider(symbol: str) -> dict:
    """Try providers in user-configured priority order for 'fundamental' category."""
    from app.context import current_user_id
    from app.providers.registry import get_prioritized_providers

    user_id = current_user_id.get("default")
    providers = get_prioritized_providers(user_id, "fundamental")

    for provider in providers:
        try:
            result = provider.get_key_metrics(symbol)
            if result:
                logger.debug("metrics:%s served by %s", symbol, provider.provider_name)
                return result
        except Exception as exc:
            logger.debug("Provider %s metrics failed for %s: %s", provider.provider_name, symbol, exc)
    return {}


@tool("get_key_metrics", args_schema=KeyMetricsInput)
def get_key_metrics(symbol: str) -> str:
    """Fetch key financial metrics and valuation ratios for a stock.

    Returns a JSON object with fields like pe_ratio, pb_ratio, roe,
    debt_to_equity, gross_margin, revenue_growth_yoy, beta, etc.
    """
    # Try configured provider first (e.g. FMP)
    data = _fetch_metrics_configured_provider(symbol)
    # Then OpenBB
    if not data:
        data = _fetch_metrics_openbb(symbol)
    # Always merge yfinance as supplement
    yf_data = _fetch_metrics_yfinance(symbol)
    if not data:
        data = yf_data
    else:
        for k, v in yf_data.items():
            if k not in data or data[k] is None:
                data[k] = v

    if not data:
        return json.dumps({"error": f"No metrics found for {symbol}"})
    return json.dumps(_sanitise(data), default=str, ensure_ascii=False)
