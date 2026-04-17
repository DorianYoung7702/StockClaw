"""SubAgent tool: resolve fuzzy user input to a validated ticker symbol.

This is a reusable "resolve first, act later" primitive. Any tool that needs
a precise ticker (watchlist add, task create, etc.) should call this first.

Resolution pipeline:
1. Direct ticker validation via yfinance (has market price?)
2. Bare digits → try .HK suffix (Hong Kong market convention)
3. yfinance fuzzy search (company name / partial match)
4. LLM-assisted name → ticker mapping (handles Chinese names like 英伟达→NVDA)
5. If multiple candidates, return them all so the caller can ask the user.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


@dataclass
class ResolvedSymbol:
    ticker: str
    name: str
    exchange: str = ""


# ---------------------------------------------------------------------------
# Internal helpers (no LLM needed)
# ---------------------------------------------------------------------------

def _get_yf_info(sym: str) -> Optional[dict]:
    """Validate a symbol via yfinance info. Returns info dict or None."""
    try:
        from app.providers.ticker_cache import get_yf_info
        info = get_yf_info(sym)
        if info and (
            info.get("regularMarketPrice")
            or info.get("currentPrice")
            or info.get("previousClose")
        ):
            return info
    except Exception:
        pass
    return None


def _yf_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Search Yahoo Finance. Returns list of {symbol, name, exchange}."""
    try:
        import yfinance as yf
        results = yf.Search(query, max_results=max_results)
        quotes = results.quotes if hasattr(results, "quotes") else []
        out = []
        for q in quotes:
            sym = q.get("symbol", "")
            name = q.get("shortname") or q.get("longname") or ""
            exchange = q.get("exchange", "")
            if sym:
                out.append({"symbol": sym, "name": name, "exchange": exchange})
        return out
    except Exception as exc:
        logger.debug("yf.Search(%r) failed: %s", query, exc)
        return []


def _data_resolve(raw: str) -> list[ResolvedSymbol]:
    """Data-only resolution (no LLM). Returns validated candidates."""
    raw = raw.strip()
    upper = raw.upper()
    candidates: list[ResolvedSymbol] = []

    # 1) Direct ticker validation
    info = _get_yf_info(upper)
    if info:
        return [ResolvedSymbol(
            ticker=upper,
            name=info.get("longName") or info.get("shortName") or upper,
            exchange=info.get("exchange", ""),
        )]

    # 2) Bare digits → try .HK
    digits_only = upper.replace(".", "")
    if digits_only.isdigit() and not upper.endswith(".HK"):
        hk_sym = f"{upper}.HK"
        info = _get_yf_info(hk_sym)
        if info:
            return [ResolvedSymbol(
                ticker=hk_sym,
                name=info.get("longName") or info.get("shortName") or hk_sym,
                exchange=info.get("exchange", ""),
            )]

    # 3) yfinance search
    hits = _yf_search(raw, max_results=5)
    for h in hits:
        info = _get_yf_info(h["symbol"])
        if info:
            candidates.append(ResolvedSymbol(
                ticker=h["symbol"],
                name=info.get("longName") or info.get("shortName") or h["name"],
                exchange=h.get("exchange", ""),
            ))
        if len(candidates) >= 3:
            break

    return candidates


# ---------------------------------------------------------------------------
# LLM-assisted resolution (SubAgent)
# ---------------------------------------------------------------------------

_RESOLVE_PROMPT = """\
You are a stock symbol resolver. Given a user query, determine the most likely ticker symbol.

Common mappings:
- 英伟达/辉达 → NVDA, 苹果 → AAPL, 特斯拉 → TSLA, 微软 → MSFT
- 腾讯 → 0700.HK, 阿里巴巴 → 9988.HK or BABA, 比亚迪 → 1211.HK or 002594.SZ
- 谷歌 → GOOGL, 亚马逊 → AMZN, 耐克 → NKE, 台积电 → TSM or 2330.TW
- 美团 → 3690.HK, 小米 → 1810.HK, 京东 → 9618.HK or JD

If the input is a number (e.g. "1428"), it is likely a Hong Kong stock code → append ".HK".
If the input is already a valid ticker format (e.g. "AAPL"), return it as-is.

Output ONLY a JSON object: {"ticker": "XXXX", "confidence": "high|medium|low"}
No markdown, no explanation."""


def _llm_resolve(raw: str) -> Optional[str]:
    """Use LLM to map a name/number to a ticker symbol."""
    try:
        from app.llm.factory import create_llm
        llm = create_llm(role="tool_calling", temperature=0.0, max_tokens=100)
        resp = llm.invoke([
            {"role": "system", "content": _RESOLVE_PROMPT},
            {"role": "user", "content": raw},
        ])
        text = resp.content.strip()
        text = re.sub(r"```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        obj = json.loads(text)
        return obj.get("ticker", "").strip().upper() or None
    except Exception as exc:
        logger.debug("LLM resolve failed for %r: %s", raw, exc)
        return None


# ---------------------------------------------------------------------------
# Main resolution function (public API)
# ---------------------------------------------------------------------------

def resolve_symbol_sync(raw: str) -> dict:
    """Full resolution pipeline. Returns dict with status + results.

    Return schema:
    - {"status": "ok", "ticker": "X", "name": "Y", "candidates": []}
    - {"status": "ambiguous", "ticker": "", "name": "", "candidates": [...]}
    - {"status": "not_found", "ticker": "", "name": "", "candidates": []}
    """
    raw = raw.strip()
    if not raw:
        return {"status": "not_found", "ticker": "", "name": "", "candidates": []}

    # Phase 1: Data-only resolution
    candidates = _data_resolve(raw)

    if len(candidates) == 1:
        c = candidates[0]
        return {"status": "ok", "ticker": c.ticker, "name": c.name, "candidates": []}

    if len(candidates) > 1:
        return {
            "status": "ambiguous",
            "ticker": "",
            "name": "",
            "candidates": [
                {"ticker": c.ticker, "name": c.name, "exchange": c.exchange}
                for c in candidates
            ],
        }

    # Phase 2: LLM-assisted (Chinese names, aliases)
    llm_ticker = _llm_resolve(raw)
    if llm_ticker:
        info = _get_yf_info(llm_ticker)
        if info:
            name = info.get("longName") or info.get("shortName") or llm_ticker
            return {"status": "ok", "ticker": llm_ticker, "name": name, "candidates": []}
        # LLM suggested but not validated — try .HK variant
        if llm_ticker.replace(".", "").isdigit() and not llm_ticker.endswith(".HK"):
            hk = f"{llm_ticker}.HK"
            info = _get_yf_info(hk)
            if info:
                name = info.get("longName") or info.get("shortName") or hk
                return {"status": "ok", "ticker": hk, "name": name, "candidates": []}

    return {"status": "not_found", "ticker": "", "name": "", "candidates": []}


# ---------------------------------------------------------------------------
# LangChain Tool wrapper
# ---------------------------------------------------------------------------

class ResolveInput(BaseModel):
    query: str = Field(description="Stock name, ticker, or code to resolve. Examples: 'AAPL', '1428', '英伟达', 'Nike'")


@tool("resolve_symbol", args_schema=ResolveInput)
def resolve_symbol(query: str) -> str:
    """Resolve a fuzzy stock name / code / ticker to a validated symbol.

    ALWAYS call this BEFORE add_to_watchlist or any action requiring a precise
    ticker symbol. Handles:
    - Exact tickers: "AAPL" → AAPL
    - HK stock codes: "1428" → 1428.HK
    - Chinese names: "英伟达" → NVDA, "腾讯" → 0700.HK
    - English names: "Nike" → NKE

    Returns the resolved ticker + company name, or candidates if ambiguous.
    If ambiguous, ask the user to pick before proceeding.
    """
    result = resolve_symbol_sync(query)
    return json.dumps(result, ensure_ascii=False)
