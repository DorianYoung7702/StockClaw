"""Thread-safe TTL cache for yfinance data.

Same ticker's ``.info``, financial statements, history, news, and calendar
are fetched once and reused across all tools within the TTL window.
Eliminates redundant HTTP requests and prevents yfinance rate-limiting.

**Snapshot fallback**: when live yfinance calls fail (rate-limit, network),
data is loaded from JSON snapshot files in ``cache/snapshots/``.
Run ``scripts/warm_demo.py`` to pre-generate snapshots.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Snapshot fallback
# ---------------------------------------------------------------------------
_SNAPSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "snapshots"


def _has_snapshot(name: str) -> bool:
    """Return True if a snapshot file exists (cheap check, no I/O read)."""
    return (_SNAPSHOT_DIR / f"{name}.json").exists()


def _load_snapshot(name: str) -> Any:
    """Load a JSON snapshot from cache/snapshots/<name>.json if it exists."""
    path = _SNAPSHOT_DIR / f"{name}.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        logger.info("snapshot FALLBACK loaded: %s", path.name)
        return data
    except Exception as exc:
        logger.debug("snapshot load failed for %s: %s", name, exc)
        return None


def _safe_sym(symbol: str) -> str:
    """Normalise symbol for snapshot filenames: AAPL, 0700_HK."""
    return symbol.replace(".", "_").upper()

_DEFAULT_TTL: float = 3600.0  # 1 hour
_NEWS_TTL: float = 1800.0  # 30 min — news changes faster
_RETRY_ATTEMPTS: int = 3
_RETRY_BASE_DELAY: float = 1.5  # seconds, doubles each retry
_RATE_LIMIT_BASE_DELAY: float = 3.0  # backoff for 429 / rate-limit (reduced from 10s)
_RATE_LIMIT_KEYWORDS: tuple[str, ...] = (
    "rate limit", "too many requests", "429",
)


# ---------------------------------------------------------------------------
# Generic TTL store
# ---------------------------------------------------------------------------

class _Entry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl: float) -> None:
        self.value = value
        self.expires_at = time.monotonic() + ttl

    @property
    def expired(self) -> bool:
        return time.monotonic() > self.expires_at


class TickerCache:
    """Singleton, thread-safe, TTL-based cache."""

    def __init__(self, default_ttl: float = _DEFAULT_TTL) -> None:
        self._default_ttl = default_ttl
        self._lock = threading.Lock()
        self._store: dict[str, _Entry] = {}

    # -- primitives ---------------------------------------------------------

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expired:
                del self._store[key]
                return None
            return entry.value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        with self._lock:
            self._store[key] = _Entry(value, ttl or self._default_ttl)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    @property
    def size(self) -> int:
        with self._lock:
            # purge expired while counting
            now = time.monotonic()
            expired = [k for k, v in self._store.items() if now > v.expires_at]
            for k in expired:
                del self._store[k]
            return len(self._store)


# Module-level singleton
_cache = TickerCache()


def get_ticker_cache() -> TickerCache:
    return _cache


# ---------------------------------------------------------------------------
# Convenience helpers — import these in tools / providers
# ---------------------------------------------------------------------------

_ticker_cache_lock = threading.Lock()
_ticker_objects: dict[str, Any] = {}


def _yf_ticker(symbol: str):
    """Return a cached yfinance Ticker object — reuses HTTP sessions."""
    key = symbol.upper()
    with _ticker_cache_lock:
        t = _ticker_objects.get(key)
        if t is not None:
            return t
    import yfinance as yf
    t = yf.Ticker(symbol)
    with _ticker_cache_lock:
        _ticker_objects[key] = t
    return t


def _is_rate_limited(exc: Exception) -> bool:
    """Return True if *exc* looks like a yfinance / HTTP 429 rate-limit error."""
    msg = str(exc).lower()
    return any(kw in msg for kw in _RATE_LIMIT_KEYWORDS)


def _retry_fetch(fn, label: str, max_attempts: int = _RETRY_ATTEMPTS) -> Any:
    """Call *fn()* with exponential-backoff retries on failure or empty result.

    Acquires the global yfinance Semaphore before each attempt so that
    concurrent callers across the whole process are throttled.
    Rate-limit errors (429) use a longer backoff schedule.

    Integrates with the Harness CircuitBreaker: when the breaker is OPEN,
    returns None immediately so the caller can fall back to snapshots.
    """
    from app.providers.market_cache import get_yf_semaphore
    from app.harness.circuit_breaker import get_breaker

    breaker = get_breaker("yfinance")

    if not breaker.allow_request():
        logger.warning("%s: CircuitBreaker OPEN — skipping to fallback", label)
        return None

    sem = get_yf_semaphore()
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with sem:
                result = fn()
                # Small delay between requests to avoid bursting
                time.sleep(0.3)
            # yfinance sometimes returns an empty dict/df on transient errors
            if result is None:
                raise ValueError(f"{label}: got None")
            if isinstance(result, dict) and not result:
                raise ValueError(f"{label}: got empty dict")
            breaker.record_success()
            return result
        except Exception as exc:
            last_exc = exc
            breaker.record_failure()
            if attempt < max_attempts:
                base = _RATE_LIMIT_BASE_DELAY if _is_rate_limited(exc) else _RETRY_BASE_DELAY
                delay = base * (2 ** (attempt - 1))
                logger.warning(
                    "%s attempt %d/%d failed (%s). Retrying in %.1fs…",
                    label, attempt, max_attempts, exc, delay,
                )
                time.sleep(delay)
            else:
                logger.warning("%s failed after %d attempts: %s", label, max_attempts, exc)
    return None  # all attempts exhausted


def get_yf_info(symbol: str) -> dict[str, Any]:
    """Cached ``yf.Ticker(symbol).info`` with retry on transient failure."""
    key = f"info:{symbol.upper()}"
    cached = _cache.get(key)
    if cached is not None:
        logger.debug("cache HIT  %s", key)
        return cached
    logger.debug("cache MISS %s — fetching from yfinance", key)
    snap_name = f"{_safe_sym(symbol)}_info"
    attempts = 1 if _has_snapshot(snap_name) else _RETRY_ATTEMPTS
    info = _retry_fetch(lambda: _yf_ticker(symbol).info or {}, f"yf.info({symbol})", max_attempts=attempts)
    if not info:
        snap = _load_snapshot(snap_name)
        if snap:
            info = snap
    if info is None:
        info = {}
    _cache.set(key, info)
    return info


_STMT_SNAPSHOT_MAP: dict[str, str] = {
    "income_stmt": "income_annual",
    "quarterly_income_stmt": "income_quarter",
    "balance_sheet": "balance_annual",
    "quarterly_balance_sheet": "balance_quarter",
    "cashflow": "cash_annual",
    "quarterly_cashflow": "cash_quarter",
}


def get_yf_statement(
    symbol: str,
    attr: str,
    period: str = "annual",
) -> Any:
    """Cached financial statement DataFrame.

    *attr* is the ``yf.Ticker`` attribute name, e.g. ``"income_stmt"``,
    ``"quarterly_balance_sheet"``, etc.
    """
    key = f"stmt:{symbol.upper()}:{attr}"
    cached = _cache.get(key)
    if cached is not None:
        return cached
    snap_suffix = _STMT_SNAPSHOT_MAP.get(attr, attr)
    snap_name = f"{_safe_sym(symbol)}_{snap_suffix}"
    attempts = 1 if _has_snapshot(snap_name) else _RETRY_ATTEMPTS
    df = _retry_fetch(
        lambda: getattr(_yf_ticker(symbol), attr, None),
        f"yf.{attr}({symbol})",
        max_attempts=attempts,
    )
    if df is None or (hasattr(df, 'empty') and df.empty):
        snap = _load_snapshot(snap_name)
        if snap:
            import pandas as pd
            df = pd.DataFrame(snap)
    _cache.set(key, df)
    return df


def get_yf_history(symbol: str, period: str = "1y", interval: str = "1d") -> Any:
    """Cached ``yf.Ticker(symbol).history(period=..., interval=...)``."""
    key = f"hist:{symbol.upper()}:{period}:{interval}"
    cached = _cache.get(key)
    if cached is not None:
        return cached
    snap_name = f"{_safe_sym(symbol)}_history_{period}_{interval}"
    attempts = 1 if _has_snapshot(snap_name) else _RETRY_ATTEMPTS
    hist = _retry_fetch(
        lambda: _yf_ticker(symbol).history(period=period, interval=interval),
        f"yf.history({symbol},{period},{interval})",
        max_attempts=attempts,
    )
    if hist is None or (hasattr(hist, 'empty') and hist.empty):
        snap = _load_snapshot(snap_name)
        if snap:
            import pandas as pd
            hist = pd.DataFrame(snap)
            if "date" in hist.columns:
                hist["date"] = pd.to_datetime(hist["date"], utc=True)
                hist = hist.set_index("date")
    if hist is None:
        import pandas as pd
        hist = pd.DataFrame()
    _cache.set(key, hist)
    return hist


def get_yf_news(symbol: str) -> list[dict[str, Any]]:
    """Cached ``yf.Ticker(symbol).news`` (shorter TTL)."""
    key = f"news:{symbol.upper()}"
    cached = _cache.get(key)
    if cached is not None:
        return cached
    snap_name = f"{_safe_sym(symbol)}_news"
    attempts = 1 if _has_snapshot(snap_name) else 2
    news = _retry_fetch(
        lambda: _yf_ticker(symbol).news or [],
        f"yf.news({symbol})",
        max_attempts=attempts,
    )
    if not news:
        snap = _load_snapshot(snap_name)
        if snap:
            news = snap
    if news is None:
        news = []
    _cache.set(key, news, ttl=_NEWS_TTL)
    return news


def get_yf_calendar(symbol: str) -> Any:
    """Cached ``yf.Ticker(symbol).calendar``."""
    key = f"cal:{symbol.upper()}"
    cached = _cache.get(key)
    if cached is not None:
        return cached
    snap_name = f"{_safe_sym(symbol)}_calendar"
    attempts = 1 if _has_snapshot(snap_name) else 2
    cal = _retry_fetch(
        lambda: _yf_ticker(symbol).calendar,
        f"yf.calendar({symbol})",
        max_attempts=attempts,
    )
    if cal is None:
        snap = _load_snapshot(snap_name)
        if snap:
            cal = snap
    _cache.set(key, cal)
    return cal


def get_yf_insider_transactions(symbol: str) -> Any:
    """Cached ``yf.Ticker(symbol).insider_transactions``."""
    key = f"insider:{symbol.upper()}"
    cached = _cache.get(key)
    if cached is not None:
        return cached
    insider = _retry_fetch(
        lambda: _yf_ticker(symbol).insider_transactions,
        f"yf.insider({symbol})",
        max_attempts=2,
    )
    _cache.set(key, insider)
    return insider
