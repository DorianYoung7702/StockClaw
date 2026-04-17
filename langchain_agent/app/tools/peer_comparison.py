"""Tool for fetching peer / industry comparison data."""

from __future__ import annotations

import json
import logging
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

SECTOR_PEERS: dict[str, list[str]] = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AVGO", "ORCL", "CRM", "AMD", "INTC"],
    "Consumer Cyclical": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "TGT", "LOW"],
    "Healthcare": ["UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT"],
    "Financial Services": ["JPM", "BAC", "GS", "MS", "V", "MA", "BRK-B", "C"],
    "Communication Services": ["GOOGL", "META", "DIS", "NFLX", "CMCSA", "T", "VZ"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX"],
    "Industrials": ["CAT", "BA", "HON", "UPS", "GE", "RTX", "LMT", "DE"],
    "Consumer Defensive": ["PG", "KO", "PEP", "COST", "WMT", "PM", "CL"],
    "Utilities": ["NEE", "DUK", "SO", "D", "AEP", "SRE"],
    "Real Estate": ["PLD", "AMT", "CCI", "EQIX", "SPG", "O"],
    "Basic Materials": ["LIN", "APD", "SHW", "ECL", "FCX", "NEM"],
}

HK_SECTOR_PEERS: dict[str, list[str]] = {
    "Technology": ["0700.HK", "9888.HK", "9999.HK", "3690.HK", "9618.HK", "0020.HK", "0992.HK", "1810.HK"],
    "Financial Services": ["0005.HK", "1398.HK", "3988.HK", "2318.HK", "0388.HK", "0011.HK", "2628.HK", "1299.HK"],
    "Consumer Cyclical": ["9961.HK", "1024.HK", "2020.HK", "0175.HK", "1928.HK", "0291.HK"],
    "Real Estate": ["0016.HK", "0001.HK", "0688.HK", "0017.HK", "2007.HK", "1109.HK", "0012.HK"],
    "Healthcare": ["2269.HK", "1177.HK", "6160.HK", "2359.HK", "1093.HK"],
    "Energy": ["0883.HK", "0857.HK", "0386.HK", "1088.HK", "2688.HK"],
    "Industrials": ["0669.HK", "3323.HK", "1766.HK", "2313.HK", "0390.HK"],
    "Communication Services": ["0941.HK", "0728.HK", "0762.HK", "1833.HK"],
    "Consumer Defensive": ["0322.HK", "2319.HK", "0151.HK", "0288.HK", "0220.HK"],
    "Utilities": ["0002.HK", "0003.HK", "0006.HK", "0270.HK", "1038.HK"],
    "Basic Materials": ["3968.HK", "2600.HK", "0914.HK", "1088.HK"],
}


class PeerComparisonInput(BaseModel):
    symbol: str = Field(description="Ticker symbol to find peers for")
    max_peers: int = Field(default=5, description="Max number of peers to compare")


def _safe(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _is_hk_symbol(symbol: str) -> bool:
    """Check if a symbol is a Hong Kong stock."""
    return symbol.upper().endswith(".HK")


def _get_fmp_peers(symbol: str) -> list[str]:
    """Fetch dynamic peer list from FMP /stock_peers endpoint."""
    from app.config import get_settings

    settings = get_settings()
    if not settings.fmp_api_key:
        return []

    from app.harness.circuit_breaker import get_breaker

    breaker = get_breaker("fmp")
    if not breaker.allow_request():
        return []

    import httpx

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                f"https://financialmodelingprep.com/api/v4/stock_peers",
                params={"symbol": symbol.upper(), "apikey": settings.fmp_api_key},
            )
            resp.raise_for_status()
            data = resp.json()
        breaker.record_success()
        if isinstance(data, list) and data:
            peers = data[0].get("peersList", [])
            return [p for p in peers if p.upper() != symbol.upper()]
    except Exception as exc:
        breaker.record_failure()
        logger.debug("FMP stock_peers failed for %s: %s", symbol, exc)
    return []


def _get_peer_symbols(symbol: str, max_peers: int) -> list[str]:
    """Find peer symbols — FMP dynamic peers first, then static sector table."""
    # Try FMP dynamic peers
    fmp_peers = _get_fmp_peers(symbol)
    if fmp_peers:
        logger.debug("peers:%s served by FMP (%d)", symbol, len(fmp_peers))
        return fmp_peers[:max_peers]

    # Fallback: static sector table
    from app.providers.ticker_cache import get_yf_info

    is_hk = _is_hk_symbol(symbol)
    peer_db = HK_SECTOR_PEERS if is_hk else SECTOR_PEERS

    try:
        info = get_yf_info(symbol)
        sector = info.get("sector", "")
    except Exception:
        sector = ""

    candidates = peer_db.get(sector, [])
    if not candidates:
        for _sector, syms in peer_db.items():
            if symbol.upper() in [s.upper() for s in syms]:
                candidates = syms
                break

    peers = [s for s in candidates if s.upper() != symbol.upper()]
    return peers[:max_peers]


def _fetch_peer_metrics(symbols: list[str]) -> list[dict]:
    """Fetch comparison metrics for a list of symbols."""
    from app.providers.ticker_cache import get_yf_info

    results = []
    for sym in symbols:
        try:
            info = get_yf_info(sym)
            results.append({
                "symbol": sym,
                "name": info.get("longName") or info.get("shortName", sym),
                "market_cap": _safe(info.get("marketCap")),
                "pe_ratio": _safe(info.get("trailingPE")),
                "forward_pe": _safe(info.get("forwardPE")),
                "pb_ratio": _safe(info.get("priceToBook")),
                "roe": _safe(info.get("returnOnEquity")),
                "revenue_growth": _safe(info.get("revenueGrowth")),
                "gross_margin": _safe(info.get("grossMargins")),
                "operating_margin": _safe(info.get("operatingMargins")),
                "net_margin": _safe(info.get("profitMargins")),
                "debt_to_equity": _safe(info.get("debtToEquity")),
            })
        except Exception as exc:
            logger.debug("Failed to fetch peer metrics for %s: %s", sym, exc)
    return results


@tool("get_peer_comparison", args_schema=PeerComparisonInput)
def get_peer_comparison(symbol: str, max_peers: int = 5) -> str:
    """Compare a stock with its industry peers on key financial metrics.

    Returns a JSON object containing the target stock's metrics alongside
    3-5 peer companies from the same sector, covering PE, ROE, margins,
    growth, and market cap for relative valuation.
    """
    peers = _get_peer_symbols(symbol, max_peers)
    if not peers:
        return json.dumps({"error": f"No peers found for {symbol}"})

    all_symbols = [symbol] + peers
    metrics = _fetch_peer_metrics(all_symbols)

    target = next((m for m in metrics if m["symbol"].upper() == symbol.upper()), None)
    peer_data = [m for m in metrics if m["symbol"].upper() != symbol.upper()]

    return json.dumps(
        {"target": target, "peers": peer_data, "sector_peer_count": len(peer_data)},
        default=str,
        ensure_ascii=False,
    )
