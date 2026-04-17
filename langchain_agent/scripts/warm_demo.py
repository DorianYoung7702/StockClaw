"""Pre-warm demo data: fetch real data for demo tickers and save as JSON snapshots.

Usage::

    python scripts/warm_demo.py              # warm all demo tickers
    python scripts/warm_demo.py AAPL TSLA    # warm specific tickers only

Snapshots are saved to ``cache/snapshots/`` and used as fallback when live API
calls fail (rate-limited, network issues, etc.).
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
logger = logging.getLogger("warm_demo")

SNAPSHOT_DIR = PROJECT_ROOT / "cache" / "snapshots"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

# Default demo tickers — covers US big tech + HK for cross-market demo
DEMO_TICKERS = ["AAPL", "NVDA", "TSLA", "MSFT", "GOOGL", "AMD", "META", "0700.HK"]

# Market types for strong stocks
DEMO_MARKETS = ["us_stock", "hk_stock"]


def _save(name: str, data: Any) -> None:
    path = SNAPSHOT_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, default=str, ensure_ascii=False, indent=2)
    logger.info("  → saved %s (%d bytes)", path.name, path.stat().st_size)


def warm_ticker(symbol: str) -> None:
    """Fetch all data types for a single ticker and save snapshots."""
    from app.providers.ticker_cache import get_yf_info, get_yf_history, get_yf_news, get_yf_statement

    logger.info("=== Warming %s ===", symbol)
    safe_sym = symbol.replace(".", "_").upper()

    # 1. Info (profile + metrics)
    try:
        info = get_yf_info(symbol)
        _save(f"{safe_sym}_info", info)
    except Exception as exc:
        logger.warning("  info failed: %s", exc)
    time.sleep(1)

    # 2. History (6mo daily)
    try:
        hist = get_yf_history(symbol, period="6mo", interval="1d")
        if hist is not None and not hist.empty:
            records = []
            for idx, row in hist.iterrows():
                records.append({
                    "date": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                    "open": float(row.get("Open", 0)),
                    "high": float(row.get("High", 0)),
                    "low": float(row.get("Low", 0)),
                    "close": float(row.get("Close", 0)),
                    "volume": int(row.get("Volume", 0)),
                })
            _save(f"{safe_sym}_history_6mo_1d", records)
    except Exception as exc:
        logger.warning("  history failed: %s", exc)
    time.sleep(1)

    # 3. History (1y daily — for risk metrics / technical)
    try:
        hist = get_yf_history(symbol, period="1y", interval="1d")
        if hist is not None and not hist.empty:
            records = []
            for idx, row in hist.iterrows():
                records.append({
                    "date": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                    "open": float(row.get("Open", 0)),
                    "high": float(row.get("High", 0)),
                    "low": float(row.get("Low", 0)),
                    "close": float(row.get("Close", 0)),
                    "volume": int(row.get("Volume", 0)),
                })
            _save(f"{safe_sym}_history_1y_1d", records)
    except Exception as exc:
        logger.warning("  history 1y failed: %s", exc)
    time.sleep(1)

    # 4. Financial statements
    for stmt_attr, label in [
        ("income_stmt", "income_annual"),
        ("balance_sheet", "balance_annual"),
        ("cashflow", "cash_annual"),
        ("quarterly_income_stmt", "income_quarter"),
    ]:
        try:
            df = get_yf_statement(symbol, stmt_attr)
            if df is not None and not df.empty:
                df_t = df.T.reset_index()
                df_t.rename(columns={"index": "period"}, inplace=True)
                records = df_t.head(4).to_dict(orient="records")
                # Sanitize
                for r in records:
                    for k, v in list(r.items()):
                        if hasattr(v, "isoformat"):
                            r[k] = v.isoformat()
                        elif isinstance(v, float) and v != v:
                            r[k] = None
                _save(f"{safe_sym}_{label}", records)
        except Exception as exc:
            logger.warning("  %s failed: %s", label, exc)
        time.sleep(0.5)

    # 5. News
    try:
        news = get_yf_news(symbol)
        if news:
            items = []
            for n in news[:10]:
                items.append({
                    "title": n.get("title", ""),
                    "url": n.get("link", ""),
                    "source": n.get("publisher", ""),
                    "published": str(n.get("providerPublishTime", "")),
                })
            _save(f"{safe_sym}_news", items)
    except Exception as exc:
        logger.warning("  news failed: %s", exc)
    time.sleep(1)

    # 6. Calendar (catalysts)
    try:
        from app.providers.ticker_cache import get_yf_calendar
        cal = get_yf_calendar(symbol)
        if cal is not None:
            cal_data = cal if isinstance(cal, dict) else cal.to_dict()
            # Serialize dates
            serialized = {}
            for k, v in cal_data.items():
                if isinstance(v, dict):
                    serialized[k] = {sk: (sv.isoformat() if hasattr(sv, "isoformat") else str(sv)) for sk, sv in v.items()}
                else:
                    serialized[k] = v.isoformat() if hasattr(v, "isoformat") else str(v)
            _save(f"{safe_sym}_calendar", serialized)
    except Exception as exc:
        logger.warning("  calendar failed: %s", exc)
    time.sleep(0.5)


def warm_market_data() -> None:
    """Fetch index snapshots for demo."""
    from app.providers.ticker_cache import get_yf_history

    logger.info("=== Warming market index snapshots ===")
    index_symbols = {
        "us_stock": ["^GSPC", "^IXIC", "^DJI", "QQQ", "SPY"],
        "hk_stock": ["^HSI", "^HSCE"],
    }
    for market, syms in index_symbols.items():
        snapshot = {}
        for sym in syms:
            try:
                hist = get_yf_history(sym, period="2d")
                if hist is not None and not hist.empty:
                    latest = hist.iloc[-1]
                    prev = hist.iloc[-2] if len(hist) > 1 else latest
                    snapshot[sym] = {
                        "price": round(float(latest["Close"]), 2),
                        "change_pct": round(
                            (float(latest["Close"]) - float(prev["Close"])) / float(prev["Close"]) * 100, 2
                        ),
                    }
            except Exception as exc:
                logger.warning("  index %s failed: %s", sym, exc)
            time.sleep(0.5)
        _save(f"index_snapshot_{market}", snapshot)


def warm_strong_stocks() -> None:
    """Run strong-stock screening and save snapshots."""
    logger.info("=== Warming strong stocks ===")
    try:
        from app.tools.strong_stocks import load_strong_stocks_with_params

        for market in DEMO_MARKETS:
            try:
                result = load_strong_stocks_with_params(market)
                _save(f"strong_stocks_{market}", result)
                logger.info("  %s: %d stocks", market, len(result.get("stocks", [])))
            except Exception as exc:
                logger.warning("  strong_stocks %s failed: %s", market, exc)
            time.sleep(2)
    except Exception as exc:
        logger.warning("  strong_stocks import failed: %s", exc)


def main():
    tickers = sys.argv[1:] if len(sys.argv) > 1 else DEMO_TICKERS

    logger.info("Demo warm-up: tickers=%s", tickers)
    logger.info("Snapshot dir: %s", SNAPSHOT_DIR)

    for t in tickers:
        try:
            warm_ticker(t)
        except Exception as exc:
            logger.error("Failed to warm %s: %s", t, exc)
        time.sleep(2)  # Inter-ticker delay to avoid rate limits

    warm_market_data()
    warm_strong_stocks()

    # Summary
    snapshot_files = list(SNAPSHOT_DIR.glob("*.json"))
    total_size = sum(f.stat().st_size for f in snapshot_files)
    logger.info("=== Done: %d snapshot files, %.1f KB total ===", len(snapshot_files), total_size / 1024)


if __name__ == "__main__":
    main()
