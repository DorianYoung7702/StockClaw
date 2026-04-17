"""Tool for fetching company profile / overview information."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

try:
    import openbb as _obb_check  # noqa: F401
    _OPENBB_AVAILABLE = True
except Exception:
    _OPENBB_AVAILABLE = False
    logger.info("OpenBB not available — company_profile will use yfinance only")


class CompanyProfileInput(BaseModel):
    symbol: str = Field(description="Ticker symbol, e.g. AAPL")


def _fetch_profile(symbol: str) -> dict:
    """Try OpenBB first, then fall back to yfinance."""
    if not _OPENBB_AVAILABLE:
        return _fetch_profile_yfinance(symbol)
    try:
        from openbb import obb

        result = obb.equity.profile(symbol=symbol, provider="yfinance")
        df = result.to_dataframe()
        if not df.empty:
            row = df.iloc[0].to_dict()
            for k, v in list(row.items()):
                if isinstance(v, float) and v != v:
                    row[k] = None
                elif hasattr(v, "isoformat"):
                    row[k] = v.isoformat()
            return row
    except Exception as exc:
        logger.debug("OpenBB profile failed for %s: %s", symbol, exc)

    return _fetch_profile_yfinance(symbol)


def _fetch_profile_yfinance(symbol: str) -> dict:
    try:
        from app.providers.ticker_cache import get_yf_info

        info = get_yf_info(symbol)
        return {
            "symbol": symbol,
            "name": info.get("longName") or info.get("shortName", ""),
            "industry": info.get("industry", ""),
            "sector": info.get("sector", ""),
            "market_cap": info.get("marketCap"),
            "currency": info.get("currency", "USD"),
            "exchange": info.get("exchange", ""),
            "description": info.get("longBusinessSummary", ""),
            "website": info.get("website", ""),
            "employees": info.get("fullTimeEmployees"),
            "country": info.get("country", ""),
        }
    except Exception as exc:
        logger.warning("yfinance profile fallback failed for %s: %s", symbol, exc)
        return {}


def _fetch_profile_configured_provider(symbol: str) -> dict:
    """Try providers in user-configured priority order for 'fundamental' category."""
    from app.context import current_user_id
    from app.providers.registry import get_prioritized_providers

    user_id = current_user_id.get("default")
    providers = get_prioritized_providers(user_id, "fundamental")

    for provider in providers:
        try:
            result = provider.get_company_profile(symbol)
            if result:
                logger.debug("profile:%s served by %s", symbol, provider.provider_name)
                return result
        except Exception as exc:
            logger.debug("Provider %s profile failed for %s: %s", provider.provider_name, symbol, exc)
    return {}


@tool("get_company_profile", args_schema=CompanyProfileInput)
def get_company_profile(symbol: str) -> str:
    """Get company overview including name, industry, sector, market cap,
    description, and other basic information.
    """
    # Try configured provider first (e.g. FMP)
    data = _fetch_profile_configured_provider(symbol)
    if not data:
        data = _fetch_profile(symbol)
    if not data:
        return json.dumps({"error": f"No profile found for {symbol}"})
    return json.dumps(data, default=str, ensure_ascii=False)
