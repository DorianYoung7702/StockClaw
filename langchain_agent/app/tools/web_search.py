"""Web search tool for supplementary news and information gathering.

Uses DuckDuckGo via the ``ddgs`` package (free, no API key) with built-in
rate limiting and exponential backoff to avoid 403 ratelimit errors.

Every result includes source attribution (title, URL, source) so the
agent can cite where the information came from.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global rate limiter: max N searches per window to avoid DuckDuckGo 403
# ---------------------------------------------------------------------------
_RATE_WINDOW_SEC = 60
_RATE_MAX_CALLS = 12  # max 12 searches per 60s across all concurrent agents
_rate_lock = threading.Lock()
_rate_timestamps: list[float] = []


class WebSearchInput(BaseModel):
    query: str = Field(description="Search query, e.g. 'AAPL earnings Q1 2025 analysis'")
    max_results: int = Field(default=5, description="Max number of results to return (1-10)")


def _rate_check() -> bool:
    """Return True if we are within the global rate limit."""
    now = time.monotonic()
    with _rate_lock:
        # Purge old timestamps
        _rate_timestamps[:] = [t for t in _rate_timestamps if now - t < _RATE_WINDOW_SEC]
        if len(_rate_timestamps) >= _RATE_MAX_CALLS:
            return False
        _rate_timestamps.append(now)
        return True


def _search_ddg(query: str, max_results: int = 5, retries: int = 2) -> list[dict]:
    """Execute DuckDuckGo text search with retry + backoff."""
    from ddgs import DDGS

    for attempt in range(retries + 1):
        if not _rate_check():
            logger.info("web_search: rate limited, waiting 5s")
            time.sleep(5)
            if not _rate_check():
                logger.warning("web_search: still rate limited, skipping")
                return []
        try:
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=min(max_results, 10)))
            results = []
            for item in raw:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("href", ""),
                    "snippet": item.get("body", ""),
                    "source": _extract_domain(item.get("href", "")),
                })
            return results
        except Exception as exc:
            err_str = str(exc).lower()
            if "ratelimit" in err_str or "403" in err_str:
                wait = 3 * (attempt + 1)
                logger.info("web_search: ratelimited (attempt %d), backoff %ds", attempt + 1, wait)
                time.sleep(wait)
            else:
                logger.warning("DuckDuckGo search failed: %s", exc)
                return []
    return []


def _search_ddg_news(query: str, max_results: int = 5) -> list[dict]:
    """Search DuckDuckGo news — single attempt, no retry (news endpoint is fragile)."""
    if not _rate_check():
        return []
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            raw = list(ddgs.news(query, max_results=min(max_results, 10)))

        results = []
        for item in raw:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("body", ""),
                "source": item.get("source", _extract_domain(item.get("url", ""))),
                "published": item.get("date", ""),
            })
        return results
    except Exception as exc:
        logger.debug("DuckDuckGo news search skipped: %s", exc)
        return []


def _extract_domain(url: str) -> str:
    """Extract domain name from URL for source attribution."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        return domain
    except Exception:
        return ""


@tool("web_search", args_schema=WebSearchInput)
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for recent news, analysis, and supplementary information.

    Use this tool to supplement financial data with broader context:
    - Recent earnings analysis or market commentary
    - Industry trends and competitive dynamics
    - Regulatory or policy developments affecting a company
    - Analyst opinions and price target changes

    IMPORTANT: Every result includes source attribution (title, URL, source).
    You MUST cite the source when using information from search results in
    your analysis. Format citations as: [来源: source_name](url)

    Returns a JSON array of search results with title, url, snippet, and source.
    """
    # Try news search first for financial queries, then general search as supplement
    news_results = _search_ddg_news(query, max_results=max_results)
    general_results = _search_ddg(query, max_results=max(2, max_results - len(news_results)))

    # Deduplicate by URL
    seen_urls: set[str] = set()
    combined: list[dict] = []
    for item in news_results + general_results:
        url = item.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            combined.append(item)

    combined = combined[:max_results]

    if not combined:
        return json.dumps({
            "error": f"No search results found for: {query}",
            "suggestion": "Try rephrasing the query or using more specific terms.",
        })

    return json.dumps({
        "query": query,
        "result_count": len(combined),
        "results": combined,
        "note": "ALWAYS cite source when using this information: [来源: source](url)",
    }, default=str, ensure_ascii=False)
