"""Finnhub company news provider.

Free tier: 60 API calls / minute.
Endpoint: GET https://finnhub.io/api/v1/company-news?symbol=AAPL&from=...&to=...
Returns title, summary (headline), url, source, datetime.

Sign up at https://finnhub.io/register and set FINNHUB_API_KEY in .env.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://finnhub.io/api/v1"


def fetch_finnhub_news(
    symbol: str,
    limit: int = 10,
    days_back: int = 7,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch company news from Finnhub.

    Returns a normalised list of dicts with keys:
    ``title``, ``url``, ``source``, ``published``, ``summary``.

    Returns an empty list when the API key is missing or calls fail.
    """
    if api_key is None:
        from app.config import get_settings

        api_key = get_settings().finnhub_api_key
    if not api_key:
        return []

    # CircuitBreaker integration
    from app.harness.circuit_breaker import get_breaker

    breaker = get_breaker("finnhub")
    if not breaker.allow_request():
        logger.warning("finnhub news: CircuitBreaker OPEN — skipping")
        return []

    today = date.today()
    from_date = (today - timedelta(days=days_back)).isoformat()
    to_date = today.isoformat()

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                f"{_BASE_URL}/company-news",
                params={
                    "symbol": symbol.upper(),
                    "from": from_date,
                    "to": to_date,
                    "token": api_key,
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
            ts = article.get("datetime")
            published = ""
            if ts:
                from datetime import datetime, timezone

                published = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

            items.append({
                "title": article.get("headline", ""),
                "url": article.get("url", ""),
                "source": article.get("source", ""),
                "published": published,
                "summary": article.get("summary", ""),
            })
        return items

    except Exception as exc:
        breaker.record_failure()
        logger.warning("Finnhub news fetch failed for %s: %s", symbol, exc)
        return []
