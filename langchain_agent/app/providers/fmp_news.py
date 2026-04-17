"""FMP (Financial Modeling Prep) company news provider.

Endpoint: GET https://financialmodelingprep.com/api/v3/stock_news?tickers=AAPL&limit=10
Returns title, text (summary), url, site (source), publishedDate.

Requires FMP_API_KEY in .env.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://financialmodelingprep.com/api/v3"


def fetch_fmp_news(
    symbol: str,
    limit: int = 10,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch company news from FMP.

    Returns a normalised list of dicts with keys:
    ``title``, ``url``, ``source``, ``published``, ``summary``.

    Returns an empty list when the API key is missing or calls fail.
    """
    if api_key is None:
        from app.config import get_settings

        api_key = get_settings().fmp_api_key
    if not api_key:
        return []

    # CircuitBreaker integration
    from app.harness.circuit_breaker import get_breaker

    breaker = get_breaker("fmp")
    if not breaker.allow_request():
        logger.warning("FMP news: CircuitBreaker OPEN — skipping")
        return []

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                f"{_BASE_URL}/stock_news",
                params={
                    "tickers": symbol.upper(),
                    "limit": limit,
                    "apikey": api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        if not isinstance(data, list):
            breaker.record_failure()
            return []

        breaker.record_success()

        items: list[dict[str, Any]] = []
        for article in data[:limit]:
            text = article.get("text", "") or ""
            items.append({
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "source": article.get("site", ""),
                "published": article.get("publishedDate", ""),
                "summary": text[:500] if text else "",
            })
        return items

    except Exception as exc:
        breaker.record_failure()
        logger.warning("FMP news fetch failed for %s: %s", symbol, exc)
        return []
