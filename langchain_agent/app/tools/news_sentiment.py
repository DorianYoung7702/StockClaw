"""Tool for fetching recent company news.

Priority chain (first success wins):
  1. Finnhub  — free, 60 req/min, has headline summary
  2. FMP      — paid, stable, full article text
  3. yfinance — free, no summary, rate-limited
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CompanyNewsInput(BaseModel):
    symbol: str = Field(description="Ticker symbol, e.g. AAPL")
    limit: int = Field(default=10, description="Max number of news items to return")


# ---------------------------------------------------------------------------
# Individual fetchers
# ---------------------------------------------------------------------------

def _fetch_finnhub(symbol: str, limit: int, user_id: str) -> list[dict]:
    """Finnhub — best quality (title + summary), free tier."""
    try:
        from app.providers.finnhub_news import fetch_finnhub_news
        from app.harness.datasource_config import get_datasource_config_store

        store = get_datasource_config_store()
        api_key = store.get_api_key(user_id, "finnhub")
        items = fetch_finnhub_news(symbol, limit=limit, api_key=api_key)
        if items:
            logger.debug("news:%s served by Finnhub (%d items)", symbol, len(items))
        return items
    except Exception as exc:
        logger.debug("Finnhub news failed for %s: %s", symbol, exc)
        return []


def _fetch_fmp(symbol: str, limit: int, user_id: str) -> list[dict]:
    """FMP — stable paid source with full article text."""
    try:
        from app.providers.fmp_news import fetch_fmp_news
        from app.harness.datasource_config import get_datasource_config_store

        store = get_datasource_config_store()
        api_key = store.get_api_key(user_id, "fmp")
        items = fetch_fmp_news(symbol, limit=limit, api_key=api_key)
        if items:
            logger.debug("news:%s served by FMP (%d items)", symbol, len(items))
        return items
    except Exception as exc:
        logger.debug("FMP news failed for %s: %s", symbol, exc)
        return []


def _fetch_yfinance(symbol: str, limit: int, user_id: str) -> list[dict]:
    """yfinance — free fallback, title only (no summary)."""
    del user_id
    try:
        from app.providers.ticker_cache import get_yf_news

        news = get_yf_news(symbol)
        items = []
        for n in (news or [])[:limit]:
            items.append({
                "title": n.get("title", ""),
                "url": n.get("link", ""),
                "source": n.get("publisher", ""),
                "published": n.get("providerPublishTime", ""),
                "summary": "",
            })
        if items:
            logger.debug("news:%s served by yfinance (%d items)", symbol, len(items))
        return items
    except Exception as exc:
        logger.warning("yfinance news fallback failed for %s: %s", symbol, exc)
        return []


# ---------------------------------------------------------------------------
# Priority chain (dynamic, reads user config)
# ---------------------------------------------------------------------------

_NEWS_FETCHERS: dict[str, Callable[[str, int, str], list[dict]]] = {
    "finnhub": _fetch_finnhub,
    "fmp": _fetch_fmp,
    "yfinance": _fetch_yfinance,
}


def _fetch_news(symbol: str, limit: int) -> list[dict]:
    """Try news sources in user-configured priority order; return first non-empty."""
    from app.context import current_user_id
    from app.harness.datasource_config import get_datasource_config_store

    user_id = current_user_id.get("default")
    store = get_datasource_config_store()
    ordered = store.get_provider_priority(user_id, "news")

    # Try configured priority order first
    tried = set()
    for name in ordered:
        fetcher = _NEWS_FETCHERS.get(name)
        if fetcher:
            tried.add(name)
            items = fetcher(symbol, limit, user_id)
            if items:
                return items

    # Fallback: try any remaining fetchers not in the priority list
    for name, fetcher in _NEWS_FETCHERS.items():
        if name not in tried:
            items = fetcher(symbol, limit, user_id)
            if items:
                return items

    return []


def fetch_company_news_items(symbol: str, limit: int = 10) -> list[dict]:
    return _fetch_news(symbol, limit)


# ---------------------------------------------------------------------------
# LangChain tool
# ---------------------------------------------------------------------------

@tool("get_company_news", args_schema=CompanyNewsInput)
def get_company_news(symbol: str, limit: int = 10) -> str:
    """Fetch recent news articles for a company. Returns a JSON array of news
    items with title, url, source, published date, and summary.

    Uses multiple professional sources (Finnhub, FMP) with yfinance fallback.
    """
    items = fetch_company_news_items(symbol, limit)
    if not items:
        return json.dumps({"error": f"No news found for {symbol}"})
    return json.dumps(items, default=str, ensure_ascii=False)
