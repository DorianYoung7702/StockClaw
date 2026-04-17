"""Upcoming macro / policy events calendar.

Returns a static list of major economic & policy events with known or
estimated dates.  These are **market-wide** events not tied to a specific
ticker, such as central-bank rate decisions, key data releases, and
fiscal/trade policy milestones.

The list is intentionally maintained by hand so that the application does
not depend on an external economic-calendar API.  Update the ``_RAW``
table periodically (monthly is fine).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# ── Raw event table ──────────────────────────────────────────────────
# Each entry: (iso-date, label, detail | None)
# Keep this list sorted by date ascending and prune past items regularly.
_RAW: list[tuple[str, str, str | None]] = [
    # ── 2026-Q2 ──
    ("2026-04-10", "CPI 数据公布",          "3月CPI · 通胀走势关键指标"),
    ("2026-04-16", "中国Q1 GDP",            "一季度经济增速"),
    ("2026-05-01", "非农就业报告",           "4月非农 · 劳动力市场核心数据"),
    ("2026-05-06", "FOMC 利率决议",         "美联储5月议息会议"),
    ("2026-05-13", "CPI 数据公布",          "4月CPI"),
    ("2026-06-05", "非农就业报告",           "5月非农"),
    ("2026-06-10", "CPI 数据公布",          "5月CPI"),
    ("2026-06-17", "FOMC 利率决议",         "美联储6月议息会议 · 含经济预测"),
    # ── 2026-Q3 ──
    ("2026-07-02", "非农就业报告",           "6月非农"),
    ("2026-07-15", "CPI 数据公布",          "6月CPI"),
    ("2026-07-16", "中国Q2 GDP",            "二季度经济增速"),
    ("2026-07-29", "FOMC 利率决议",         "美联储7月议息会议"),
    ("2026-08-07", "非农就业报告",           "7月非农"),
    ("2026-08-12", "CPI 数据公布",          "7月CPI"),
    ("2026-09-04", "非农就业报告",           "8月非农"),
    ("2026-09-10", "CPI 数据公布",          "8月CPI"),
    ("2026-09-16", "FOMC 利率决议",         "美联储9月议息会议 · 含经济预测"),
]


_CACHE_TTL: float = 86400.0  # 24 hours — data is static, only changes daily
_cache: dict[str, tuple[float, list[dict]]] = {}  # key → (expires_at, events)


def get_upcoming_policy_events(
    horizon_days: int = 90,
    lookback_days: int = 30,
) -> list[dict]:
    """Return policy events within *horizon_days* from today.

    Also includes recently-past events within *lookback_days* so the
    frontend can show "已发生" events for review.

    Each dict mirrors the ``WatchlistEvent`` shape used by the frontend:
    ``{ ticker, event, date, days_away, detail?, category }``
    with ``ticker`` set to ``"宏观"`` and ``category`` set to ``"policy"``.

    Results are cached for 24 hours since the underlying data is static.
    """
    import time

    cache_key = f"policy_{horizon_days}_{lookback_days}"
    now = time.monotonic()
    cached = _cache.get(cache_key)
    if cached and now < cached[0]:
        return cached[1]

    today = date.today()
    start = today - timedelta(days=lookback_days)
    cutoff = today + timedelta(days=horizon_days)
    events: list[dict] = []

    for iso, label, detail in _RAW:
        try:
            d = date.fromisoformat(iso)
        except ValueError:
            logger.warning("Invalid date in policy calendar: %s", iso)
            continue
        if d < start or d > cutoff:
            continue
        events.append({
            "ticker": "宏观",
            "event": label,
            "date": d.isoformat(),
            "days_away": (d - today).days,
            "detail": detail,
            "category": "policy",
        })

    _cache[cache_key] = (now + _CACHE_TTL, events)
    return events
