"""Individual node implementations for the main LangGraph graph."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.fundamental import RECURSION_LIMIT as FUND_LIMIT
from app.agents.fundamental import create_fundamental_agent
from app.agents.sentiment import RECURSION_LIMIT as SENT_LIMIT
from app.agents.sentiment import create_sentiment_agent
from app.agents.synthesis import synthesise
from app.config import get_settings
from app.llm.factory import get_tool_calling_llm
from app.memory.rag_evidence import ingest_news_event_documents, retrieve_fundamental_evidence, retrieve_news_evidence
from app.prompts.response_policy import augment_system_prompt
from app.models.state import AgentState
from app.tools import get_strong_stocks
from app.tools.news_sentiment import fetch_company_news_items
from app.harness.context import TokenBudgetManager, estimate_tokens
from app.harness.compaction import compact_conversation
from app.harness.recovery import recoverable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Parse input — rules-first, LLM fallback
# ---------------------------------------------------------------------------

# Regex patterns for fast classification (no LLM needed)
_STRONG_RE = re.compile(
    r"强势股|强势|筛选.{0,4}(美股|港股|ETF|基金)|监控池|screening"
    r"|^(美股|港股|ETF).{0,6}(强|涨|好|推荐|排[名行])"
    r"|给我.{0,6}(强势|涨|股)",
    re.IGNORECASE,
)
_COMPARE_RE = re.compile(r"对比|比较|compare|vs\.?\s", re.IGNORECASE)
_CONFIG_RE = re.compile(
    r"(改|换|调|设).{0,4}(RSI|rsi|阈值|前\d|排序|成交|市场|数量)"
    r"|按.{0,4}排序|top.?\d",
    re.IGNORECASE,
)
_WATCHLIST_RE = re.compile(r"加入.{0,4}(观察|自选|关注)|add.{0,4}watch", re.IGNORECASE)
# Adjustment language — when combined with _STRONG_RE, means config change, not fetch
_ADJUST_RE = re.compile(
    r"不要那么多|少[一点些]|多[一点些给]|就行|就够|够了"
    r"|改[成为]|换[成为]|调[成为整]",
    re.IGNORECASE,
)
_ANALYZE_KW_RE = re.compile(
    r"分析|基本面|研究|看看.{0,2}(财务|基本面|估值)"
    r"|analyze|research|fundamental",
    re.IGNORECASE,
)
# Ticker patterns: US (AAPL, GOOGL) and HK (0700, 1211, 9988, with optional .HK)
# NOTE: \b doesn't work at CJK-ASCII boundaries (both are \w in Python 3).
# Use negative lookaround on [A-Za-z] for US tickers and [0-9] for HK codes.
_TICKER_RE = re.compile(
    r"(?<![A-Za-z])([A-Z]{1,5})(?![A-Za-z])"   # US ticker
    r"|(?<!\d)(\d{4,5})(?:\.HK)?(?!\d)"          # HK numeric code
)
_TICKER_STOP = frozenset({
    "I", "A", "AI", "API", "CEO", "CFO", "CTO", "COO", "IPO", "ETF",
    "GDP", "PE", "PB", "ROE", "EPS", "RSI", "MACD", "SMA", "EMA",
    "ATR", "OK", "HTTP", "SSE", "URL", "JSON", "CSV", "SQL", "USD",
    "HKD", "CNY", "EUR", "GBP", "THE", "FOR", "AND", "NOT", "BUT",
    "TOP", "VS", "OR",
})
# HK numeric codes that should get .HK suffix
_HK_CODE_RE = re.compile(r"\b(\d{4,5})(?:\.HK)?\b")
_HK_CONTEXT_RE = re.compile(r"港股|HK|恒生|香港|.HK", re.IGNORECASE)
# Market extraction from text
_MARKET_RE_MAP = [
    (re.compile(r"港股|HK|恒生|香港", re.IGNORECASE), "hk_stock"),
    (re.compile(r"美股|US|美国|纳斯达克|标普", re.IGNORECASE), "us_stock"),
    (re.compile(r"ETF|基金|指数", re.IGNORECASE), "etf"),
]


def _extract_market(text: str) -> Optional[str]:
    for pat, mt in _MARKET_RE_MAP:
        if pat.search(text):
            return mt
    return None


def _extract_tickers(text: str) -> list[str]:
    """Extract US and HK tickers from text."""
    tickers: list[str] = []
    has_hk_context = bool(_HK_CONTEXT_RE.search(text))

    for m in _TICKER_RE.finditer(text):
        us, hk_num = m.group(1), m.group(2)
        if us and us not in _TICKER_STOP:
            tickers.append(us)
        elif hk_num:
            code = hk_num.lstrip("0") or "0"
            # 4-5 digit numbers in HK context → add .HK suffix
            if has_hk_context or ".HK" in text.upper():
                tickers.append(f"{hk_num}.HK")
            else:
                tickers.append(f"{hk_num}.HK")  # default HK for bare numbers
    return tickers


_ZH_NUMS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
             "十五": 15, "二十": 20, "三十": 30, "五十": 50}


def _extract_top_count(text: str) -> Optional[int]:
    # Arabic digits: "10只", "前20只"
    m = re.search(r"(\d{1,3})\s*[只个支只隻]", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(?:前|top)\s*(\d{1,3})", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Chinese numerals: "十个", "二十只", "五个"
    zh_pat = "|".join(sorted(_ZH_NUMS.keys(), key=len, reverse=True))
    m = re.search(rf"({zh_pat})\s*[只个支隻]", text)
    if m:
        return _ZH_NUMS.get(m.group(1))
    return None


def _fast_parse(text: str) -> Optional[dict[str, Any]]:
    """Fast-path — currently disabled. All classification goes through LLM."""
    return None



_INTENT_SYSTEM = """\
You are a routing classifier for a stock analysis application.
Output ONLY a valid JSON object — no markdown fences, no extra text, nothing else.

## Multi-intent support
A single user message may contain **multiple intents**. You MUST identify ALL of them.
Examples:
- "分析AAPL并加入观察组" → TWO intents: single_stock(AAPL) + watchlist_add(AAPL)
- "帮我研究腾讯 然后换成港股" → TWO intents: single_stock(0700.HK) + update_config(hk_stock)
- "把NKE加观察组然后分析一下" → TWO intents: watchlist_add(NKE) + single_stock(NKE)
- "分析苹果" → ONE intent: single_stock(AAPL)

JSON schema:
{
  "intents": [
    {"intent": "<type>", "tickers": ["AAPL"], "screening_params": {}}
  ]
}

Each element in "intents" has:
- intent: single_stock | compare | update_config | multi_step | chat | watchlist_add | watchlist_remove
- tickers: relevant tickers for THIS intent ([] if none)
- screening_params: only for update_config, otherwise omit or {}

screening_params schema (include only fields the user mentioned):
  {"market_type": "us_stock|hk_stock|etf", "top_count": N, "rsi_threshold": F,
   "sort_by": "momentum_score|performance_20d|rs_20d|vol_score|trend_r2",
   "min_volume_turnover": F}

Intent rules:
- single_stock  : User wants a fundamental / deep analysis of a specific stock.
    Examples: "分析苹果", "TSLA基本面分析", "帮我研究一下AMD", "看看NVDA财务"
- compare       : compare two or more stocks side-by-side
- update_config : screening/monitoring list OR change screening params ("给我强势股", "筛选美股", "换成港股")
- multi_step    : complex request requiring multiple sequential analyses
- watchlist_add : add stock to watchlist. Examples: "把NVDA加入观察组", "NKE加自选"
- watchlist_remove : remove stock from watchlist. Examples: "把NKE移出观察组"
- chat          : greetings, usage questions, follow-up questions on EXISTING analysis, anything that doesn't fit above.

HARD RULE — ALWAYS single_stock, NEVER chat:
If the message contains an analysis keyword (分析/基本面/研究/看看…财务/估值/analyze/research/fundamental)
AND mentions a specific stock name or ticker → that part MUST be "single_stock" (or "compare" if multiple).

EXCEPTION — use chat for follow-ups:
If the RECENT conversation already contains a completed analysis for the SAME stock,
and the user asks a follow-up without re-requesting analysis → intent=chat.

IMPORTANT: Do NOT use "strong_stocks" intent. Use "update_config" for all screening/monitoring requests.

Coreference resolution:
- Pronouns "它"/"这个"/"那只"/"this"/"it" → resolve from recent conversation history.
- Example: prior analysis was AAPL, user says "把它加观察组" → intents: [watchlist_add(AAPL)]

Extraction rules:
- Map names: 英伟达→NVDA, 苹果→AAPL, Tesla/特斯拉→TSLA, 腾讯→0700.HK, 谷歌→GOOGL
- Market: 美股=us_stock  港股=hk_stock  ETF/基金=etf
- Sort  : 综合动量=momentum_score  涨幅=performance_20d  超额=rs_20d  量价=vol_score  趋势=trend_r2
- Volume: 亿×1e8  万×1e4
- Output ONLY the raw JSON object, nothing else"""


class _ScreeningParams(BaseModel):
    market_type: Optional[str] = None
    top_count: Optional[int] = None
    rsi_threshold: Optional[float] = None
    sort_by: Optional[str] = None
    min_volume_turnover: Optional[float] = None


# --- Simple intents that are fast (< 1s) and should run first in the queue ---
_SIMPLE_INTENTS = frozenset({"chat", "update_config", "watchlist_add", "watchlist_remove"})


class _IntentItem(BaseModel):
    """One intent in a multi-intent queue."""
    intent: Literal[
        "single_stock", "strong_stocks", "compare", "chat",
        "update_config", "multi_step", "watchlist_add", "watchlist_remove",
    ]
    tickers: list[str] = Field(default_factory=list)
    screening_params: _ScreeningParams = Field(default_factory=_ScreeningParams)


class _IntentOutput(BaseModel):
    """LLM output — supports both legacy single-intent and multi-intent."""
    # New multi-intent field
    intents: list[_IntentItem] = Field(default_factory=list)
    # Legacy single-intent fields (for backward compat with older prompt cache)
    intent: Optional[str] = None
    tickers: list[str] = Field(default_factory=list)
    screening_params: _ScreeningParams = Field(default_factory=_ScreeningParams)

    def to_queue(self) -> list[dict[str, Any]]:
        """Normalise to a list of queue items, handling both old and new format."""
        items: list[dict[str, Any]] = []
        if self.intents:
            for it in self.intents:
                sp = {k: v for k, v in it.screening_params.model_dump().items() if v is not None}
                items.append({
                    "intent": it.intent if it.intent != "strong_stocks" else "update_config",
                    "tickers": [t for t in it.tickers if t],
                    "screening_params": sp,
                    "simple": it.intent in _SIMPLE_INTENTS,
                })
        elif self.intent:
            # Legacy single-intent format
            sp = {k: v for k, v in self.screening_params.model_dump().items() if v is not None}
            items.append({
                "intent": self.intent if self.intent != "strong_stocks" else "update_config",
                "tickers": [t for t in self.tickers if t],
                "screening_params": sp,
                "simple": self.intent in _SIMPLE_INTENTS,
            })
        else:
            items.append({"intent": "chat", "tickers": [], "screening_params": {}, "simple": True})
        # Sort: simple intents first (FIFO)
        items.sort(key=lambda x: (0 if x["simple"] else 1))
        return items


async def _build_run_debrief(session_id: str) -> str:
    """Build a concise debrief from the last run's Journal for this session.

    Returns an empty string if no prior run exists or on any error.
    The debrief gives downstream nodes awareness of what happened last time:
    quality score, recovery events, missing dimensions, etc.
    """
    if not session_id:
        return ""
    try:
        import aiosqlite
        from app.config import get_settings
        settings = get_settings()
        db_path = settings.harness_journal_db_path or settings.checkpoint_db_path

        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute(
                "SELECT entry_json FROM run_journal "
                "WHERE session_id = ? ORDER BY created_at DESC LIMIT 30",
                (session_id,),
            )
            rows = await cursor.fetchall()

        if not rows:
            return ""

        # Parse entries and extract key signals
        reflections = []
        validations = []
        recoveries = []
        for (entry_json,) in rows:
            entry = json.loads(entry_json)
            et = entry.get("event_type", "")
            payload = entry.get("payload", {})
            if et == "harness_reflection":
                reflections.append(payload)
            elif et == "harness_validation":
                validations.append(payload)
            elif et in ("harness_recovery", "recovery"):
                recoveries.append(payload)

        parts: list[str] = []
        if reflections:
            last_r = reflections[0]
            parts.append(f"上次报告质量={last_r.get('score', '?')}/10")
            missing = last_r.get("checklist_missing", [])
            if missing:
                parts.append(f"缺失维度: {', '.join(missing)}")
        if validations:
            issues = validations[0].get("total_issues", 0)
            if issues:
                parts.append(f"验证问题={issues}")
        if recoveries:
            parts.append(f"恢复事件={len(recoveries)}")

        return "; ".join(parts) if parts else ""

    except Exception as exc:
        logger.debug("_build_run_debrief failed (non-fatal): %s", exc)
        return ""


async def parse_input_node(state: AgentState) -> dict[str, Any]:
    """Classify user intent: rules-first (~0ms), LLM fallback (2-3s).

    Builds an ``intent_queue`` (sorted simple-first) and sets the first
    item as the active ``intent`` so existing routing works unchanged.
    """
    messages = state["messages"]
    last_human = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            last_human = m.content
            break

    logger.info("parse_input: classifying (input=%r)", last_human[:80])

    # ── Harness: build run debrief from prior Journal (non-blocking) ──────
    session_id = state.get("session_id", "")
    run_debrief = await _build_run_debrief(session_id)
    if run_debrief:
        logger.info("parse_input: injecting run_debrief=%s", run_debrief[:80])

    # ── Layer 1: regex fast-path ──────────────────────────────────────────
    fast = _fast_parse(last_human)
    if fast is not None:
        intent = fast["intent"]
        tickers = fast.get("tickers", [])
        logger.info("parse_input: FAST intent=%s tickers=%s", intent, tickers)
        if intent in ("single_stock", "compare") and tickers:
            await adispatch_custom_event("ticker_select", {"ticker": tickers[0], "intent": intent})
        queue = [{"intent": intent, "tickers": tickers,
                  "screening_params": fast.get("screening_params", {}),
                  "simple": intent in _SIMPLE_INTENTS}]
        result: dict[str, Any] = {
            "intent": intent,
            "tickers": tickers,
            "intent_queue": queue,
            "intent_queue_index": 0,
            "intent_results": [],
            "current_step": "parsed_input",
            "errors": [],
        }
        if run_debrief:
            result["run_debrief"] = run_debrief
        sp = fast.get("screening_params")
        if sp:
            result["screening_params"] = sp
        return result

    # ── Layer 2: LLM structured-output classifier ─────────────────────────
    llm = get_tool_calling_llm()
    parsed: Optional[_IntentOutput] = None

    # Build recent conversation context so LLM can detect follow-up questions
    context_msgs: list[dict[str, str]] = [{"role": "system", "content": _INTENT_SYSTEM}]
    recent = messages[-(min(len(messages), 7)):-1] if len(messages) > 1 else []
    for m in recent:
        if isinstance(m, HumanMessage):
            context_msgs.append({"role": "user", "content": m.content[:200]})
        elif isinstance(m, AIMessage) and m.content:
            context_msgs.append({"role": "assistant", "content": m.content[:200]})
    context_msgs.append({"role": "user", "content": last_human})

    for attempt in range(2):  # one retry on parse failure
        try:
            resp = await llm.ainvoke(context_msgs)
            raw = resp.content.strip()
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw.strip())
            idx = raw.find("{")
            if idx < 0:
                raise ValueError("No JSON object found in LLM response")
            obj, _ = json.JSONDecoder().raw_decode(raw, idx)
            parsed = _IntentOutput.model_validate(obj)
            break
        except Exception as exc:
            logger.warning(
                "parse_input: LLM classifier attempt %d failed (%s)",
                attempt + 1, exc,
            )
            if attempt == 0:
                await asyncio.sleep(0.5)

    if parsed is None:
        logger.warning("parse_input: all LLM attempts failed — defaulting to chat")
        parsed = _IntentOutput(intent="chat")

    # ── Build intent queue (simple-first) ─────────────────────────────────
    queue = parsed.to_queue()
    logger.info("parse_input: intent_queue=%s", [q["intent"] for q in queue])

    # Pick the first item as the active intent
    first = queue[0]
    intent = first["intent"]
    tickers = first["tickers"]

    # Multi-ticker single_stock → compare
    if intent == "single_stock" and len(tickers) > 1:
        logger.info("parse_input: multi-ticker (%d) → compare", len(tickers))
        await adispatch_custom_event("multi_analyze", {"tickers": tickers, "original_intent": intent})
        intent = "compare"
        first["intent"] = "compare"

    logger.info("parse_input: active intent=%s tickers=%s (queue_len=%d)", intent, tickers, len(queue))

    # Emit custom event so SSE handler can short-circuit for analysis intents
    if intent in ("single_stock", "compare") and tickers:
        await adispatch_custom_event("ticker_select", {"ticker": tickers[0], "intent": intent})

    result: dict[str, Any] = {
        "intent": intent,
        "tickers": tickers,
        "intent_queue": queue,
        "intent_queue_index": 0,
        "intent_results": [],
        "current_step": "parsed_input",
        "errors": [],
    }
    if run_debrief:
        result["run_debrief"] = run_debrief
    sp_dict = first.get("screening_params", {})
    if sp_dict:
        result["screening_params"] = sp_dict
    return result


# ---------------------------------------------------------------------------
# 1b. Resolve symbol — validate tickers via yfinance
# ---------------------------------------------------------------------------

_RESOLVE_SYSTEM = """\
You are a financial symbol resolver. Given a list of possible company names or
ticker symbols, output a JSON object:
{"resolved": [{"input": "<original>", "ticker": "<STANDARD_TICKER>"}]}

Rules:
- Map common company names to their US ticker: 英伟达->NVDA, 苹果->AAPL,
  微软->MSFT, 谷歌->GOOGL, 特斯拉->TSLA, 亚马逊->AMZN, 台积电->TSM, etc.
- If it already looks like a valid ticker (all uppercase letters), keep it as-is.
- Hong Kong stocks should keep their .HK suffix.
- Output ONLY the JSON object.
"""


def _yf_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Search Yahoo Finance for a company name → list of {symbol, name, exchange}.

    Returns an empty list on failure (non-blocking fallback).
    """
    try:
        import yfinance as yf
        results = yf.Search(query, max_results=max_results)
        quotes = results.quotes if hasattr(results, "quotes") else []
        out: list[dict[str, str]] = []
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


async def resolve_symbol_node(state: AgentState) -> dict[str, Any]:
    """Resolve company names to standard ticker symbols and validate them.

    When multiple valid candidates are found for an ambiguous input, the node
    sets ``ambiguous_tickers`` which causes the graph router to pause at
    ``human_confirm`` (interrupt node) and wait for the user to choose.
    """
    tickers = state.get("tickers", [])
    errors: list[str] = list(state.get("errors", []))

    if not tickers:
        return {
            "resolved_symbol": "",
            "errors": errors + ["No ticker or company name provided."],
            "current_step": "resolve_symbol_empty",
        }

    needs_resolve = any(
        not t.replace(".", "").replace("-", "").isascii() or not t.isupper()
        for t in tickers
    )

    resolved_tickers = list(tickers)
    if needs_resolve:
        llm = get_tool_calling_llm()
        resp = await llm.ainvoke(
            [
                {"role": "system", "content": _RESOLVE_SYSTEM},
                {"role": "user", "content": json.dumps(tickers)},
            ]
        )
        text = resp.content.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        try:
            parsed = json.loads(text)
            resolved_tickers = [
                item.get("ticker", item.get("input", ""))
                for item in parsed.get("resolved", [])
            ]
        except (json.JSONDecodeError, AttributeError):
            pass

    validated: list[str] = []
    ticker_names: dict[str, str] = {}
    original_inputs = list(tickers)  # keep raw user inputs for search fallback
    for idx, sym in enumerate(resolved_tickers):
        if not sym:
            continue

        # Determine if this still looks like a company name rather than a ticker
        _is_name = (
            not sym.replace(".", "").replace("-", "").isascii()
            or (sym != sym.upper() and not sym.endswith(".HK"))
        )

        # If it looks like a company name, try yfinance search first
        if _is_name:
            search_query = sym
            logger.info("resolve_symbol: '%s' looks like a name, searching Yahoo Finance", sym)
            hits = await asyncio.to_thread(_yf_search, search_query, 5)
            if hits:
                best = hits[0]
                logger.info("resolve_symbol: yf.Search('%s') → %s (%s)", search_query, best["symbol"], best["name"])
                sym = best["symbol"]
                if best["name"]:
                    ticker_names[sym] = best["name"]
            else:
                # Name search failed — ask user for ticker code
                logger.warning("resolve_symbol: could not resolve name '%s'", search_query)
                await adispatch_custom_event("resolve_fail", {
                    "query": search_query,
                    "message": f"未能识别「{search_query}」对应的标的，请直接输入股票代码（如 2595.HK、AAPL）",
                })
                continue  # skip this unresolved name

        try:
            from app.providers.ticker_cache import get_yf_info

            info = await asyncio.to_thread(get_yf_info, sym)
            if info and info.get("regularMarketPrice") is not None:
                validated.append(sym)
            elif info and (info.get("currentPrice") or info.get("previousClose")):
                validated.append(sym)
            else:
                # Last resort: if validation failed and we haven't searched yet,
                # try yfinance search with the original user input
                if not _is_name and idx < len(original_inputs):
                    raw = original_inputs[idx]
                    hits = await asyncio.to_thread(_yf_search, raw, 3)
                    if hits:
                        fallback = hits[0]["symbol"]
                        logger.info("resolve_symbol: fallback search '%s' → %s", raw, fallback)
                        info = await asyncio.to_thread(get_yf_info, fallback)
                        if info and (info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose")):
                            sym = fallback
                            validated.append(sym)
                            if hits[0]["name"]:
                                ticker_names[sym] = hits[0]["name"]
                            continue
                errors.append(f"Symbol '{sym}' could not be verified — data may be limited.")
                validated.append(sym)
            # Extract company name from yfinance info
            if info and sym not in ticker_names:
                name = info.get("shortName") or info.get("longName") or ""
                if name:
                    ticker_names[sym] = name
        except Exception:
            errors.append(f"Failed to validate symbol '{sym}', proceeding anyway.")
            validated.append(sym)

    primary = validated[0] if validated else ""

    # Human-in-the-loop: if original input was ambiguous (e.g. bare company name
    # that maps to multiple possible tickers), flag for confirmation.
    # The graph router sends execution to ``human_confirm`` which pauses and
    # waits for the caller to call ``graph.update_state({"ambiguous_tickers": []}``
    # with the chosen ticker before resuming.
    ambiguous = (
        validated
        if needs_resolve and len(validated) > 1
        else []
    )

    # Re-emit ticker_select with resolved name so frontend can display it
    if primary and ticker_names.get(primary):
        await adispatch_custom_event("ticker_select", {
            "ticker": primary,
            "name": ticker_names[primary],
            "intent": state.get("intent", "single_stock"),
        })

    return {
        "tickers": validated,
        "resolved_symbol": primary,
        "ticker_names": ticker_names,
        "ambiguous_tickers": ambiguous,
        "errors": errors,
        "current_step": "symbol_resolved",
    }


# ---------------------------------------------------------------------------
# 1c. Human-confirm node (Human-in-the-loop disambiguation)
# ---------------------------------------------------------------------------


async def human_confirm_node(state: AgentState) -> dict[str, Any]:
    """Interrupt node for ticker disambiguation.

    Execution reaches here only when ``resolve_symbol`` found multiple valid
    candidates and set ``ambiguous_tickers``.  The graph is compiled with
    ``interrupt_before=["human_confirm"]`` so LangGraph saves state and pauses
    *before* entering this node.

    The caller resumes by calling::

        graph.update_state(
            config,
            {"ambiguous_tickers": [], "resolved_symbol": "CHOSEN_TICKER", "tickers": ["CHOSEN_TICKER"]},
            as_node="human_confirm",
        )

    This node itself just clears the ambiguity flag so the router proceeds
    to ``retrieve_fundamental_rag``.
    """
    chosen = (state.get("resolved_symbol") or "").strip()
    tickers = state.get("tickers", [])
    if not chosen and tickers:
        chosen = tickers[0]
    return {
        "ambiguous_tickers": [],
        "resolved_symbol": chosen,
        "tickers": [chosen] if chosen else tickers,
        "current_step": "human_confirmed",
    }


# ---------------------------------------------------------------------------
# 2. Data-gathering node (single stock or compare)
# ---------------------------------------------------------------------------


async def _warm_cache(symbol: str) -> None:
    """Pre-fetch all yfinance data for *symbol* in small batches.

    Runs at most 2 requests concurrently with a short gap between batches
    to avoid triggering yfinance / Yahoo rate-limits.
    Failed fetches are retried once after a longer delay.
    """
    from app.providers.ticker_cache import (
        get_yf_calendar,
        get_yf_history,
        get_yf_info,
        get_yf_insider_transactions,
        get_yf_news,
        get_yf_statement,
    )

    fetch_fns = [
        ("info", lambda: get_yf_info(symbol)),
        ("income_stmt", lambda: get_yf_statement(symbol, "income_stmt")),
        ("balance_sheet", lambda: get_yf_statement(symbol, "balance_sheet")),
        ("cashflow", lambda: get_yf_statement(symbol, "cashflow")),
        ("history", lambda: get_yf_history(symbol, "1y")),
        ("news", lambda: get_yf_news(symbol)),
        ("calendar", lambda: get_yf_calendar(symbol)),
        ("insider", lambda: get_yf_insider_transactions(symbol)),
    ]

    _BATCH_SIZE = 2
    failed: list[tuple[str, Any]] = []

    for i in range(0, len(fetch_fns), _BATCH_SIZE):
        batch = fetch_fns[i : i + _BATCH_SIZE]
        tasks = [asyncio.to_thread(fn) for _, fn in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for (name, fn), result in zip(batch, results):
            if isinstance(result, Exception):
                logger.warning("Cache warm-up %s failed for %s: %s", name, symbol, result)
                failed.append((name, fn))
        # Brief pause between batches to spread out requests
        if i + _BATCH_SIZE < len(fetch_fns):
            await asyncio.sleep(0.5)

    if failed:
        logger.info("Warm-up: %d/%d fetches failed for %s (snapshots used where available)",
                     len(failed), len(fetch_fns), symbol)


async def _ensure_minimum_tool_coverage(symbol: str, agent_messages: list) -> str:
    """Check which fundamental tools the Agent missed and call them directly.

    Returns supplementary text to append to the fundamental report.
    """
    from app.tools.company_profile import get_company_profile
    from app.tools.key_metrics import get_key_metrics
    from app.tools.financial_statements import get_financial_statements
    from app.tools.risk_metrics import get_risk_metrics

    # Detect which tools the Agent already called by scanning tool-call messages
    called_tools: set[str] = set()
    for m in agent_messages:
        if hasattr(m, "tool_calls"):
            for tc in m.tool_calls:
                called_tools.add(tc.get("name", ""))
        # Also detect ToolMessage names
        if hasattr(m, "name") and m.name:
            called_tools.add(m.name)

    required = {
        "get_company_profile": lambda: get_company_profile.invoke({"symbol": symbol}),
        "get_key_metrics": lambda: get_key_metrics.invoke({"symbol": symbol}),
        "get_financial_statements": lambda: get_financial_statements.invoke(
            {"symbol": symbol, "statement_type": "income", "period": "annual", "limit": 4}
        ),
        "get_risk_metrics": lambda: get_risk_metrics.invoke({"symbol": symbol}),
    }

    missing = {name: fn for name, fn in required.items() if name not in called_tools}
    if not missing:
        return ""

    logger.info(
        "Agent missed %d tools for %s: %s — invoking directly",
        len(missing), symbol, list(missing.keys()),
    )

    supplement_parts: list[str] = []
    for tool_name, fn in missing.items():
        try:
            result = await asyncio.to_thread(fn)
            supplement_parts.append(f"\n### Supplementary: {tool_name}\n{result}")
        except Exception as exc:
            logger.warning("Direct %s call failed for %s: %s", tool_name, symbol, exc)
            supplement_parts.append(f"\n### Supplementary: {tool_name}\n[FAILED: {exc}]")

    return "\n".join(supplement_parts)


@recoverable(max_retry=2, base_delay=1.0, timeout_seconds=120, degradable=True)
async def gather_data_node(state: AgentState) -> dict[str, Any]:
    """Run the fundamental ReAct agent to collect financial data."""
    tickers = state.get("tickers", [])
    if not tickers:
        return {
            "financial_data": {},
            "current_step": "gather_data_skipped",
            "messages": [AIMessage(content="No tickers specified for analysis.")],
        }

    # Pre-warm yfinance cache for all tickers concurrently
    await asyncio.gather(*[_warm_cache(t) for t in tickers])

    ticker_str = ", ".join(tickers)
    rag = (state.get("retrieved_fundamental_context") or "").strip()
    rag_block = ""
    if rag:
        rag_block = (
            "\n\n## Deep filing excerpts (RAG — uploaded 10-K / annual report / MD&A text)\n"
            "Use these for qualitative depth: MD&A narrative, risk factors, business segments, "
            "management discussion. If any figure conflicts with tool-sourced data below, "
            "prefer the tools as the authoritative structured numbers.\n\n"
            f"{rag}\n"
        )
    query = (
        f"Please gather comprehensive fundamental data for: {ticker_str}\n"
        "Make sure to fetch: company profile, key metrics, income statement, "
        "balance sheet, peer comparison, and risk metrics."
    ) + rag_block

    agent = create_fundamental_agent()
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=query)]},
        config={"recursion_limit": FUND_LIMIT},
    )

    final_content = ""
    for m in reversed(result.get("messages", [])):
        if isinstance(m, AIMessage) and m.content:
            final_content = m.content
            break

    # Ensure minimum tool coverage — directly call any tools the Agent skipped
    primary_ticker = tickers[0]
    supplement = await _ensure_minimum_tool_coverage(
        primary_ticker, result.get("messages", [])
    )
    if supplement:
        final_content += f"\n\n---\n## Supplementary Data (auto-fetched)\n{supplement}"

    return {
        "financial_data": {"fundamental_text": final_content, "tickers": tickers},
        "current_step": "data_gathered",
        "messages": [AIMessage(content=f"[Fundamental data collected for {ticker_str}]")],
    }


# ---------------------------------------------------------------------------
# 2b. Supervisor node — dynamic multi-agent delegation
# ---------------------------------------------------------------------------


async def supervisor_node(state: AgentState) -> dict[str, Any]:
    """Supervisor that dynamically delegates to sub-agents based on intent.

    Demonstrates the **Supervisor pattern** — the main graph acts as a project
    manager that decides which specialist sub-agents to invoke, runs them in
    parallel, and merges their results.

    Sub-agents are compiled LangGraph sub-graphs with independent state,
    preventing cross-contamination of messages or data.
    """
    from app.agents.fundamental import create_fundamental_subgraph
    from app.agents.sentiment import create_sentiment_subgraph

    tickers = state.get("tickers", [])
    intent = state.get("intent", "single_stock")
    if not tickers:
        return {
            "financial_data": {},
            "current_step": "supervisor_skipped",
            "messages": [AIMessage(content="No tickers for supervisor delegation.")],
        }

    # Pre-warm yfinance cache
    await asyncio.gather(*[_warm_cache(t) for t in tickers])

    # Decide which sub-agents to delegate to
    delegates: list[str] = []
    if intent in ("single_stock", "compare"):
        delegates.append("fundamental")
        delegates.append("sentiment")
    elif intent == "strong_stocks":
        delegates.append("fundamental")
    else:
        delegates.append("fundamental")

    logger.info("Supervisor delegating to: %s for tickers=%s", delegates, tickers)

    # Run sub-graphs in parallel
    results: dict[str, str] = {}

    async def _run_fundamental():
        subgraph = create_fundamental_subgraph()
        r = await subgraph.ainvoke({"tickers": tickers, "messages": [], "result_text": ""})
        results["fundamental"] = r.get("result_text", "")

    async def _run_sentiment():
        subgraph = create_sentiment_subgraph()
        r = await subgraph.ainvoke({"tickers": tickers, "messages": [], "result_text": ""})
        results["sentiment"] = r.get("result_text", "")

    tasks = []
    if "fundamental" in delegates:
        tasks.append(_run_fundamental())
    if "sentiment" in delegates:
        tasks.append(_run_sentiment())

    await asyncio.gather(*tasks, return_exceptions=True)

    # Ensure minimum tool coverage on fundamental results
    fundamental_text = results.get("fundamental", "")
    if fundamental_text and tickers:
        primary = tickers[0]
        # Build a minimal messages list for coverage check
        from langchain_core.messages import AIMessage as _AI
        mock_msgs = [_AI(content=fundamental_text)]
        supplement = await _ensure_minimum_tool_coverage(primary, mock_msgs)
        if supplement:
            fundamental_text += f"\n\n---\n## Supplementary Data (auto-fetched)\n{supplement}"

    ticker_str = ", ".join(tickers)
    financial_data: dict[str, Any] = {"tickers": tickers}
    if fundamental_text:
        financial_data["fundamental_text"] = fundamental_text
    sentiment_text = results.get("sentiment", "")
    if sentiment_text:
        financial_data["sentiment_text"] = sentiment_text

    return {
        "financial_data": financial_data,
        "current_step": "supervisor_done",
        "messages": [AIMessage(content=f"[Supervisor: delegated {delegates} for {ticker_str}]")],
    }


# ---------------------------------------------------------------------------
# 2c. Dynamic Planning — Plan-and-Execute loop
# ---------------------------------------------------------------------------

_PLAN_SYSTEM = """\
You are a task planner for a stock analysis system.
Given a complex user request, break it into ordered steps. Each step must be one of:
- {"action": "analyze", "ticker": "AAPL", "description": "..."}
- {"action": "compare", "tickers": ["AAPL", "MSFT"], "description": "..."}
- {"action": "summarize", "description": "Summarize all analyses above"}

Output JSON only:
{"steps": [{"action": "...", "ticker": "...", "tickers": [], "description": "..."}]}
"""


async def plan_node(state: AgentState) -> dict[str, Any]:
    """Generate an execution plan for multi_step intent."""
    last_human = ""
    for m in reversed(state.get("messages", [])):
        if isinstance(m, HumanMessage):
            last_human = m.content
            break

    from app.llm.factory import get_tool_calling_llm
    llm = get_tool_calling_llm()

    try:
        resp = await llm.ainvoke([
            {"role": "system", "content": _PLAN_SYSTEM},
            {"role": "user", "content": last_human},
        ])
        raw = resp.content or ""
        start = raw.find("{")
        parsed = json.loads(raw[start:])
        steps = parsed.get("steps", [])
        logger.info("Plan generated: %d steps", len(steps))
    except Exception as exc:
        logger.warning("Plan generation failed, fallback to single analysis: %s", exc)
        tickers = state.get("tickers", [])
        steps = [{"action": "analyze", "ticker": t, "description": f"Analyze {t}"} for t in tickers]
        if len(tickers) > 1:
            steps.append({"action": "summarize", "description": "Summarize all analyses"})

    return {
        "execution_plan": steps,
        "plan_step_index": 0,
        "current_step": "plan_generated",
    }


async def execute_step_node(state: AgentState) -> dict[str, Any]:
    """Execute one step of the dynamic plan, then advance the index.

    - ``analyze`` → delegates to supervisor_node for a single ticker
    - ``compare`` → delegates to supervisor_node for multiple tickers
    - ``summarize`` → LLM summarises all accumulated results
    """
    plan = state.get("execution_plan", [])
    idx = state.get("plan_step_index", 0)

    if idx >= len(plan):
        return {"current_step": "plan_complete"}

    step = plan[idx]
    action = step.get("action", "analyze")
    description = step.get("description", "")
    logger.info("Executing plan step %d/%d: action=%s desc=%s", idx + 1, len(plan), action, description[:60])

    result_parts: list[str] = []
    fd = dict(state.get("financial_data", {}))

    if action == "summarize":
        # Use LLM to summarise accumulated data
        from app.llm.factory import get_reasoning_llm
        llm = get_reasoning_llm()
        accumulated = fd.get("fundamental_text", "") + "\n" + fd.get("sentiment_text", "")
        try:
            resp = await llm.ainvoke([
                {"role": "system", "content": "You are a financial analyst. Summarize the following analyses concisely in Chinese."},
                {"role": "user", "content": accumulated[:6000]},
            ])
            result_parts.append(resp.content or "")
        except Exception as exc:
            result_parts.append(f"Summary generation failed: {exc}")
    else:
        # analyze or compare → delegate to supervisor
        ticker_str = step.get("ticker", "")
        tickers_list = step.get("tickers", [])
        if ticker_str:
            tickers_list = [ticker_str]
        if not tickers_list:
            tickers_list = state.get("tickers", [])[:1]

        # Build a mini-state for supervisor
        mini_state = dict(state)
        mini_state["tickers"] = tickers_list
        mini_state["intent"] = "single_stock" if len(tickers_list) == 1 else "compare"

        supervisor_result = await supervisor_node(mini_state)
        sub_fd = supervisor_result.get("financial_data", {})
        # Merge sub-results into accumulated financial_data
        for k, v in sub_fd.items():
            if k in fd and isinstance(fd[k], str) and isinstance(v, str):
                fd[k] = fd[k] + f"\n\n--- Step {idx + 1}: {description} ---\n" + v
            else:
                fd[k] = v

    new_fd = fd
    if result_parts:
        summary_key = f"plan_step_{idx}_summary"
        new_fd[summary_key] = "\n".join(result_parts)
        # Also append to fundamental_text for synthesis
        existing = new_fd.get("fundamental_text", "")
        new_fd["fundamental_text"] = existing + f"\n\n## Plan Summary\n{''.join(result_parts)}"

    return {
        "financial_data": new_fd,
        "plan_step_index": idx + 1,
        "current_step": f"plan_step_{idx + 1}_done",
        "messages": [AIMessage(content=f"[Plan step {idx + 1}/{len(plan)}: {description}]")],
    }


# ---------------------------------------------------------------------------
# 3. Strong-stocks node
# ---------------------------------------------------------------------------

async def strong_stocks_node(state: AgentState) -> dict[str, Any]:
    """Fetch strong-stock list using parameters extracted from natural language.

    If the user specified a market / filters, apply them.
    If no market was specified, fetch both US + HK as default and append a
    guidance hint so the user knows they can refine.
    """
    from app.tools.strong_stocks import load_strong_stocks_with_params

    params: dict[str, Any] = state.get("screening_params") or {}
    market = params.get("market_type")
    tool_kwargs = {
        k: params[k]
        for k in ("top_count", "rsi_threshold", "sort_by", "min_volume_turnover")
        if k in params
    }

    if market:
        # User specified a single market → fetch with extracted params
        data = await asyncio.to_thread(
            load_strong_stocks_with_params, market, **tool_kwargs
        )
        stocks = data.get("stocks", [])
        market_label = {"us_stock": "美股", "hk_stock": "港股", "etf": "ETF"}.get(market, market)
        combined = json.dumps(
            {"market_type": market, "count": len(stocks), "stocks": stocks},
            default=str, ensure_ascii=False,
        )
    else:
        # No market specified → default fetch US + HK in parallel
        data_us, data_hk = await asyncio.gather(
            asyncio.to_thread(load_strong_stocks_with_params, "us_stock", **tool_kwargs),
            asyncio.to_thread(load_strong_stocks_with_params, "hk_stock", **tool_kwargs),
        )
        result_us = json.dumps(
            {"market_type": "us_stock", "count": len(data_us.get("stocks", [])),
             "stocks": data_us.get("stocks", [])},
            default=str, ensure_ascii=False,
        )
        result_hk = json.dumps(
            {"market_type": "hk_stock", "count": len(data_hk.get("stocks", [])),
             "stocks": data_hk.get("stocks", [])},
            default=str, ensure_ascii=False,
        )
        combined = f"US Stocks:\n{result_us}\n\nHK Stocks:\n{result_hk}"
        market_label = "美股 + 港股"

    # Build a summary of which params were applied
    param_parts = [f"市场: {market_label}"]
    if "top_count" in tool_kwargs:
        param_parts.append(f"数量: 前{tool_kwargs['top_count']}只")
    if "rsi_threshold" in tool_kwargs:
        param_parts.append(f"RSI>{tool_kwargs['rsi_threshold']}")
    if "sort_by" in tool_kwargs:
        sort_labels = {
            "momentum_score": "综合动量", "performance_20d": "20日涨幅",
            "rs_20d": "超额收益", "vol_score": "量价配合", "trend_r2": "趋势平滑",
        }
        param_parts.append(f"排序: {sort_labels.get(tool_kwargs['sort_by'], tool_kwargs['sort_by'])}")
    if "min_volume_turnover" in tool_kwargs:
        vol = tool_kwargs["min_volume_turnover"]
        param_parts.append(f"最小成交额: {vol/1e8:.1f}亿" if vol >= 1e8 else f"最小成交额: {vol/1e4:.0f}万")
    param_summary = " | ".join(param_parts)

    # Guidance hint when user didn't specify much
    guidance = ""
    missing = []
    if not market:
        missing.append("市场类型（美股/港股/ETF）")
    if "top_count" not in tool_kwargs:
        missing.append("数量（如 前10只）")
    if "sort_by" not in tool_kwargs:
        missing.append("排序方式（动量/涨幅/超额/量价/趋势）")
    if "rsi_threshold" not in tool_kwargs:
        missing.append("RSI阈值（如 RSI>55）")

    if missing:
        missing_lines = "\n".join(f"  - {m}" for m in missing)
        guidance = (
            f"\n\n💡 **你还可以指定更多条件来精确筛选**，例如：\n"
            f"{missing_lines}\n"
            f"  - 试试说：「筛选港股前10只强势股 按超额排序 RSI>60 成交额>5亿」"
        )

    result: dict[str, Any] = {
        "financial_data": {"strong_stocks_text": combined, "screening_params_applied": param_summary},
        "current_step": "strong_stocks_fetched",
        "screening_params": params,
        "messages": [AIMessage(content=f"[强势股筛选完成 — {param_summary}]{guidance}")],
    }
    # Sync screening params to frontend config so chip bar / config drawer stay current
    if params:
        result["config_update"] = params
    return result


# ---------------------------------------------------------------------------
# 4a. Update-config node  (intent = update_config)
# ---------------------------------------------------------------------------

_SORT_LABELS_ZH: dict[str, str] = {
    "momentum_score": "综合动量",
    "performance_20d": "20日涨幅",
    "performance_40d": "40日涨幅",
    "performance_90d": "90日涨幅",
    "performance_180d": "180日涨幅",
    "rs_20d": "超额收益",
    "vol_score": "量价配合",
    "trend_r2": "趋势平滑",
    "volume_5d_avg": "5日成交额",
}
_MARKET_LABELS_ZH: dict[str, str] = {
    "us_stock": "美股", "hk_stock": "港股", "etf": "ETF",
}


async def update_config_node(state: AgentState) -> dict[str, Any]:
    """Apply natural-language screening-parameter changes and echo a completion message."""
    params: dict[str, Any] = state.get("screening_params") or {}

    if not params:
        return {
            "messages": [AIMessage(content=(
                "没有识别到具体的筛选参数，请说明要调整什么，例如：\n"
                "「把美股RSI阈值改成65，前20只，按超额排序」"
            ))],
            "current_step": "config_update_failed",
        }

    parts: list[str] = []
    if "market_type" in params:
        parts.append(f"市场: {_MARKET_LABELS_ZH.get(params['market_type'], params['market_type'])}")
    if "top_count" in params:
        parts.append(f"数量: 前{params['top_count']}只")
    if "rsi_threshold" in params:
        parts.append(f"RSI>{params['rsi_threshold']}")
    if "sort_by" in params:
        parts.append(f"排序: {_SORT_LABELS_ZH.get(params['sort_by'], params['sort_by'])}")
    if "min_volume_turnover" in params:
        vol = params["min_volume_turnover"]
        parts.append(f"最小成交额: {vol/1e8:.1f}亿" if vol >= 1e8 else f"最小成交额: {vol/1e4:.0f}万")

    summary = " | ".join(parts) if parts else "（无变化）"
    msg = (
        f"✅ **监控参数已更新**\n\n"
        f"{summary}\n\n"
        f"配置已生效，点击「应用配置」即可用新参数重新筛选候选股。"
    )

    return {
        "config_update": params,
        "messages": [AIMessage(content=msg)],
        "current_step": "config_updated",
    }


# ---------------------------------------------------------------------------
# 4b. Watchlist-add node  (intent = watchlist_add | analyze_and_watch fan-in)
# ---------------------------------------------------------------------------


async def watchlist_add_node(state: AgentState) -> dict[str, Any]:
    """Add resolved ticker(s) to the user's watchlist and return a completion message."""
    from app.memory.watchlist import add_ticker  # lazy import — watchlist is optional

    # Prefer the resolved symbol (from resolve_symbol_node) if available
    resolved = state.get("resolved_symbol", "")
    tickers: list[str] = [resolved.upper()] if resolved else [
        t.upper() for t in (state.get("tickers") or [])
    ]

    if not tickers:
        return {
            "messages": [AIMessage(content=(
                "没有识别到要加入观察组的股票代码，"
                "请指定具体的股票，例如：「把NVDA加入观察组」"
            ))],
            "current_step": "watchlist_add_failed",
            "financial_data": {"watchlist_result": []},
        }

    added: list[str] = []
    for ticker in tickers:
        try:
            await add_ticker("default-user", ticker, note="")
            added.append(ticker)
        except Exception as exc:
            logger.warning("watchlist_add failed for %s: %s", ticker, exc)

    if added:
        added_str = "、".join(added)
        msg = (
            f"✅ **已加入观察组**：{added_str}\n\n"
            f"可在侧边栏「观察组」页面查看和管理你的监控列表。"
        )
    else:
        msg = "⚠️ 观察组更新失败，请稍后重试。"

    return {
        "watchlist_update": added,
        "messages": [AIMessage(content=msg)],
        "current_step": "watchlist_updated",
        "financial_data": {"watchlist_result": added},
    }


# ---------------------------------------------------------------------------
# 4. Sentiment node
# ---------------------------------------------------------------------------


@recoverable(max_retry=2, base_delay=1.0, timeout_seconds=60, degradable=True)
async def sentiment_node(state: AgentState) -> dict[str, Any]:
    """Run the sentiment ReAct agent on the tickers.

    Runs **in parallel** with ``gather_data_node`` (fan-out from
    ``retrieve_fundamental_rag``).  This node writes only ``sentiment_text``
    to ``financial_data``; the merge reducer on ``AgentState`` combines it
    with ``fundamental_text`` from ``gather_data`` before ``synthesis`` runs.
    """
    tickers = state.get("tickers", [])
    if not tickers:
        return {
            "financial_data": {"sentiment_text": ""},
            "retrieved_news_context": "",
            "retrieval_debug": {"news": {"status": "skipped", "hit_count": 0}},
            "current_step": "sentiment_skipped",
            "messages": [AIMessage(content="No tickers for sentiment analysis.")],
        }

    ticker_str = ", ".join(tickers)
    session_id = (state.get("session_id") or "").strip()
    last_human = ""
    for m in reversed(state.get("messages", [])):
        if isinstance(m, HumanMessage):
            last_human = m.content
            break

    evidence_items: list[dict[str, Any]] = []
    retrieved_news_blocks: list[str] = []
    per_ticker_debug: dict[str, Any] = {}
    source_distribution: dict[str, int] = {}
    raw_item_count = 0

    if session_id:
        for symbol in tickers:
            raw_items = await asyncio.to_thread(fetch_company_news_items, symbol, 12)
            raw_item_count += len(raw_items)
            if raw_items:
                await asyncio.to_thread(
                    ingest_news_event_documents,
                    raw_items,
                    session_id=session_id,
                    ticker=symbol,
                )
            news_query = f"{last_human}\n{symbol}".strip() or f"{symbol} recent news sentiment catalysts risks"
            retrieved = await asyncio.to_thread(
                retrieve_news_evidence,
                news_query,
                session_id=session_id,
                ticker=symbol,
            )
            cur_items = retrieved.get("items", [])
            if cur_items:
                evidence_items.extend(cur_items)
                ctx = (retrieved.get("context") or "").strip()
                if ctx:
                    retrieved_news_blocks.append(f"## {symbol} News Evidence\n{ctx}")
                for item in cur_items:
                    label = str(item.get("source_label") or "news")
                    source_distribution[label] = source_distribution.get(label, 0) + 1
            cur_debug = dict(retrieved.get("debug") or {})
            cur_debug["raw_item_count"] = len(raw_items)
            per_ticker_debug[symbol] = cur_debug

    seen_evidence_ids: set[str] = set()
    deduped_evidence: list[dict[str, Any]] = []
    for item in evidence_items:
        key = str(item.get("id") or "")
        if key and key in seen_evidence_ids:
            continue
        if key:
            seen_evidence_ids.add(key)
        deduped_evidence.append(item)

    news_context = "\n\n".join(retrieved_news_blocks)
    agent = create_sentiment_agent()
    agent_prompt = f"Analyse recent news sentiment for: {ticker_str}"
    if news_context:
        agent_prompt += (
            "\n\n## Retrieved news evidence (vector recall)\n"
            "Use these items as high-signal evidence for catalysts, risks, and market tone.\n\n"
            f"{news_context}"
        )
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=agent_prompt)]},
        config={"recursion_limit": SENT_LIMIT},
    )

    final_content = ""
    for m in reversed(result.get("messages", [])):
        if isinstance(m, AIMessage) and m.content:
            final_content = m.content
            break

    return {
        "financial_data": {"sentiment_text": final_content},
        "retrieved_news_context": news_context,
        "evidence_chain": deduped_evidence,
        "retrieval_debug": {
            "news": {
                "status": "ok" if deduped_evidence else ("no_session" if not session_id else "empty"),
                "query": last_human,
                "hit_count": len(deduped_evidence),
                "raw_item_count": raw_item_count,
                "source_distribution": source_distribution,
                "per_ticker": per_ticker_debug,
            }
        },
        "current_step": "sentiment_done",
        "messages": [AIMessage(content=f"[Sentiment analysis done for {ticker_str}]")],
    }


# ---------------------------------------------------------------------------
# 4b. Retrieve session-scoped fundamental RAG (Chroma)
# ---------------------------------------------------------------------------


async def retrieve_fundamental_rag_node(state: AgentState) -> dict[str, Any]:
    """Adaptive RAG with 3 stages: Query Router → Retrieve → Relevance Grader.

    Stage 1 — **Query Router**: LLM quickly decides whether to retrieve, skip,
    or rewrite the query for better retrieval quality.

    Stage 2 — **Retrieve**: Standard Chroma similarity search (existing logic).

    Stage 3 — **Relevance Grader**: LLM evaluates whether retrieved chunks are
    actually relevant. If not, rewrites the query and retries (max 1 retry).
    """
    if not get_settings().fundamental_rag_enabled:
        return {
            "retrieved_fundamental_context": "",
            "retrieval_debug": {"filing": {"status": "disabled", "hit_count": 0}},
            "current_step": "fundamental_rag_skipped",
        }

    session_id = (state.get("session_id") or "").strip()
    if not session_id:
        return {
            "retrieved_fundamental_context": "",
            "retrieval_debug": {"filing": {"status": "no_session", "hit_count": 0}},
            "current_step": "fundamental_rag_no_session",
        }

    last_human = ""
    for m in reversed(state.get("messages", [])):
        if isinstance(m, HumanMessage):
            last_human = m.content
            break

    tickers = state.get("tickers") or []
    resolved = (state.get("resolved_symbol") or "").strip()
    ticker = resolved or (tickers[0] if tickers else "")
    original_query = f"{last_human}\n{ticker}".strip()

    # ------------------------------------------------------------------
    # Stage 1 — Query Router (LLM decides: retrieve / skip / rewrite)
    # ------------------------------------------------------------------
    async def _rag_route(query: str) -> tuple[str, str]:
        """Returns (decision, effective_query). decision in {retrieve, skip, rewrite}."""
        from app.llm.factory import get_tool_calling_llm
        llm = get_tool_calling_llm()
        router_prompt = [
            {"role": "system", "content": (
                "You are a query router for a financial RAG system.\n"
                "Given the user query, decide:\n"
                "A) 'retrieve' — query needs deep filing/document context (10-K, annual report, MD&A)\n"
                "B) 'skip' — query can be answered from real-time tools alone (price, metrics, news)\n"
                "C) 'rewrite' — query is too vague for good retrieval; rewrite it for better matching\n\n"
                "Output JSON only: {\"decision\": \"retrieve|skip|rewrite\", \"rewritten_query\": \"...\"}\n"
                "If decision is not 'rewrite', set rewritten_query to empty string."
            )},
            {"role": "user", "content": query},
        ]
        try:
            resp = await llm.ainvoke(router_prompt)
            raw = resp.content or ""
            parsed = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            decision = parsed.get("decision", "retrieve")
            rewritten = parsed.get("rewritten_query", "")
            logger.info("RAG route decision=%s for query: %s", decision, query[:60])
            if decision == "rewrite" and rewritten.strip():
                return "retrieve", rewritten.strip()
            return decision, query
        except Exception as exc:
            logger.debug("RAG router LLM failed, defaulting to retrieve: %s", exc)
            return "retrieve", query

    decision, effective_query = await _rag_route(original_query)

    if decision == "skip":
        logger.info("Adaptive RAG: skipping retrieval (router decision)")
        return {
            "retrieved_fundamental_context": "",
            "retrieval_debug": {
                "filing": {
                    "status": "skipped",
                    "query": original_query,
                    "effective_query": effective_query,
                    "hit_count": 0,
                }
            },
            "current_step": "fundamental_rag_skipped",
        }

    # ------------------------------------------------------------------
    # Stage 2 — Retrieve from Chroma
    # ------------------------------------------------------------------
    def _do_retrieve(q: str) -> dict[str, Any]:
        return retrieve_fundamental_evidence(q, session_id=session_id, ticker=ticker or None)

    retrieval = await asyncio.to_thread(_do_retrieve, effective_query)
    ctx = (retrieval.get("context") or "").strip()
    evidence_items = retrieval.get("items", [])
    retrieval_debug = dict(retrieval.get("debug") or {})
    retrieval_debug["effective_query"] = effective_query

    if not ctx.strip():
        return {
            "retrieved_fundamental_context": "",
            "evidence_chain": [],
            "retrieval_debug": {"filing": retrieval_debug},
            "current_step": "fundamental_rag_empty",
        }

    # ------------------------------------------------------------------
    # Stage 3 — Relevance Grader (evaluate + optional rewrite retry)
    # ------------------------------------------------------------------
    async def _rag_grade(query: str, context: str) -> bool:
        """Return True if context is relevant to query."""
        from app.llm.factory import get_tool_calling_llm
        llm = get_tool_calling_llm()
        grade_prompt = [
            {"role": "system", "content": (
                "You are a relevance grader for a financial RAG system.\n"
                "Evaluate whether the retrieved document chunks are relevant to the user query.\n"
                "Output JSON only: {\"relevant\": true/false, \"reason\": \"brief explanation\"}"
            )},
            {"role": "user", "content": (
                f"Query: {query}\n\nRetrieved context (first 1500 chars):\n{context[:1500]}"
            )},
        ]
        try:
            resp = await llm.ainvoke(grade_prompt)
            raw = resp.content or ""
            parsed = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            relevant = parsed.get("relevant", True)
            logger.info("RAG grade: relevant=%s reason=%s", relevant, parsed.get("reason", "")[:60])
            return bool(relevant)
        except Exception as exc:
            logger.debug("RAG grader LLM failed, assuming relevant: %s", exc)
            return True

    is_relevant = await _rag_grade(effective_query, ctx)

    if not is_relevant:
        # Rewrite query and retry once
        logger.info("Adaptive RAG: context deemed irrelevant, rewriting query and retrying")
        _, rewritten_query = await _rag_route(
            f"改写以下查询以更好地匹配年报/10-K文档内容：{original_query}"
        )
        retrieval_retry = await asyncio.to_thread(_do_retrieve, rewritten_query)
        ctx_retry = (retrieval_retry.get("context") or "").strip()
        if ctx_retry:
            ctx = ctx_retry
            evidence_items = retrieval_retry.get("items", [])
            retrieval_debug = dict(retrieval_retry.get("debug") or {})
            retrieval_debug["effective_query"] = rewritten_query
            retrieval_debug["rewrite_from_query"] = effective_query

    return {
        "retrieved_fundamental_context": ctx,
        "evidence_chain": evidence_items,
        "retrieval_debug": {"filing": retrieval_debug},
        "current_step": "fundamental_rag_retrieved",
    }


# ---------------------------------------------------------------------------
# 5. Synthesis node — produces structured JSON + markdown
# ---------------------------------------------------------------------------

_MARKET_LABELS_MD = {"us_stock": "美股", "hk_stock": "港股", "etf": "ETF"}


def _format_strong_stocks_md(raw_json: str, param_summary: str) -> str:
    """Convert strong-stocks JSON into a readable markdown table."""
    def _fmt(v: Any, suffix: str = "%") -> str:
        if v is None:
            return "-"
        return f"{float(v):.1f}{suffix}"

    def _fmts(v: Any) -> str:
        if v is None:
            return "-"
        return f"{float(v):.2f}"

    def _render_block(data: dict) -> str:
        market = data.get("market_type", "")
        label = _MARKET_LABELS_MD.get(market, market)
        stocks = data.get("stocks", [])
        if not stocks:
            return f"### {label}\n\n暂无符合条件的强势股。\n"

        lines = [
            f"## {label} 强势股 ({len(stocks)} 只)",
            "",
            "| # | 代码 | 价格 | 20日 | 90日 | 超额 | 量价 | 趋势R² | 综合分 |",
            "|---|------|------|------|------|------|------|--------|--------|",
        ]
        for i, s in enumerate(stocks, 1):
            lines.append(
                f"| {i} | {s.get('symbol', '')} | {_fmts(s.get('current_price'))} "
                f"| {_fmt(s.get('performance_20d'))} | {_fmt(s.get('performance_90d'))} "
                f"| {_fmt(s.get('rs_20d'))} | {_fmts(s.get('vol_score'))} "
                f"| {_fmts(s.get('trend_r2'))} | {_fmts(s.get('momentum_score'))} |"
            )
        return "\n".join(lines)

    try:
        # May be a single JSON object or two blocks separated by "US Stocks:" / "HK Stocks:"
        if raw_json.strip().startswith("{"):
            data = json.loads(raw_json)
            body = _render_block(data)
        else:
            parts = []
            for segment in raw_json.split("\n\n"):
                segment = segment.strip()
                if segment.startswith(("US Stocks:", "HK Stocks:")):
                    segment = segment.split(":", 1)[1].strip()
                if segment.startswith("{"):
                    parts.append(_render_block(json.loads(segment)))
            body = "\n\n".join(parts) if parts else raw_json

        header = f"**筛选条件**: {param_summary}\n\n" if param_summary else ""
        return f"{header}{body}"
    except Exception:
        return f"# 强势股筛选结果\n\n{raw_json}"


async def synthesis_node(state: AgentState) -> dict[str, Any]:
    """Produce the final investment report with structured output."""
    fd = state.get("financial_data", {})
    fundamental_text = fd.get("fundamental_text", "")
    sentiment_text = fd.get("sentiment_text", "")
    strong_text = fd.get("strong_stocks_text", "")
    resolved = state.get("resolved_symbol", "")

    user_query = ""
    for m in state["messages"]:
        if isinstance(m, HumanMessage):
            user_query = m.content
            break

    if strong_text and not fundamental_text:
        report = _format_strong_stocks_md(strong_text, fd.get("screening_params_applied", ""))
        return {
            "analysis_result": {"report": report},
            "structured_report": None,
            "current_step": "synthesis_done",
            "messages": [AIMessage(content=report)],
        }

    combined_fundamental = fundamental_text
    if strong_text:
        combined_fundamental += f"\n\n## Strong Stocks Context\n{strong_text}"

    rag_ctx = (state.get("retrieved_fundamental_context") or "").strip()
    news_rag_ctx = (state.get("retrieved_news_context") or "").strip()

    # ── Harness: budget tracking for synthesis pipeline ──────────────────
    from app.harness.context import TokenBudgetManager
    from app.config import get_settings as _get_settings
    _settings = _get_settings()
    synth_budget = TokenBudgetManager(model_limit=_settings.harness_model_context_limit)
    synth_budget.record("tool_results", combined_fundamental + (sentiment_text or ""))

    # ── Long-term memory: inject historical analysis for comparison ────────
    user_id = state.get("user_id", "")
    if user_id and resolved:
        try:
            from app.harness.long_term_memory import LongTermMemory
            ltm = await LongTermMemory.create()
            history_entries = await ltm.recall(user_id, "analysis_history", top_k=3)
            await ltm.close()
            ticker_history = [e for e in history_entries if e.key.startswith(resolved)]
            if ticker_history:
                hist_lines = [f"- {e.key}: {e.content}" for e in ticker_history]
                hist_text = "\n".join(hist_lines)
                hist_text = synth_budget.trim_to_budget("long_term_memory", hist_text)
                if hist_text:
                    combined_fundamental += (
                        "\n\n## 历史分析参考（Previous Analysis）\n"
                        + hist_text
                    )
                    synth_budget.record("long_term_memory", hist_text)
                logger.debug("synthesis_node: injected %d historical entries for %s", len(ticker_history), resolved)
        except Exception as exc:
            logger.warning("synthesis_node: LTM read failed: %s", exc)

    # If this is a revision pass, prepend reflection feedback to the query
    revision_count = state.get("revision_count", 0)
    reflection_feedback = state.get("reflection_feedback", "")
    effective_query = user_query
    if revision_count > 0 and reflection_feedback:
        effective_query = (
            f"{user_query}\n\n"
            f"## 审稿反馈（请针对性改进）\n{reflection_feedback}"
        )
        logger.info("Synthesis revision pass #%d with reflection feedback", revision_count)

    structured, markdown = await synthesise(
        fundamental_text=combined_fundamental,
        sentiment_text=sentiment_text or "No sentiment data available.",
        user_query=effective_query,
        ticker=resolved,
        retrieved_fundamental_context=rag_ctx,
        retrieved_news_context=news_rag_ctx,
    )

    result: dict[str, Any] = {
        "analysis_result": {"report": markdown},
        "structured_report": structured,
        "current_step": "synthesis_done",
        "messages": [AIMessage(content="[Synthesis complete]")],
    }
    # Track revision count for the reflection loop
    if revision_count > 0:
        result["revision_count"] = revision_count

    # ── Long-term memory: persist analysis summary (fire-and-forget) ───────
    user_id = state.get("user_id", "")
    if user_id and resolved and structured:
        asyncio.create_task(_save_analysis_memory(user_id, resolved, structured))

    return result


async def _save_analysis_memory(user_id: str, ticker: str, structured: dict) -> None:
    """Extract a concise summary from structured_report and persist to LongTermMemory."""
    import time as _time
    try:
        from app.harness.long_term_memory import LongTermMemory
        ltm = await LongTermMemory.create()

        parts: list[str] = []
        if structured.get("executive_summary"):
            parts.append(structured["executive_summary"][:200])
        for h in (structured.get("highlights") or [])[:3]:
            parts.append(f"亮点: {h}")
        for r in (structured.get("risk_factors") or [])[:3]:
            parts.append(f"风险: {r}")
        if structured.get("recommendation"):
            parts.append(f"结论: {structured['recommendation']}")

        content = " | ".join(parts) if parts else f"{ticker} 分析完成"
        key = f"{ticker}_{int(_time.time())}"
        await ltm.remember(user_id, "analysis_history", key, content)
        await ltm.close()
        logger.debug("LTM: saved analysis_history for %s/%s", user_id, ticker)
    except Exception as exc:
        logger.warning("LTM: failed to save analysis memory: %s", exc)


# ---------------------------------------------------------------------------
# 6. Validate result — check that key analysis dimensions are covered
# ---------------------------------------------------------------------------

_REQUIRED_DIMENSIONS = [
    ("profitability", ["gross_margin", "operating_margin", "net_margin", "roe"]),
    ("growth", ["revenue_growth_yoy", "earnings_growth_yoy"]),
    ("valuation", ["pe_ratio", "pb_ratio", "ev_to_ebitda"]),
    ("financial_health", ["debt_to_equity", "current_ratio"]),
]


async def validate_result_node(state: AgentState) -> dict[str, Any]:
    """Check structured report for completeness; tag missing dimensions with details."""
    errors: list[str] = list(state.get("errors", []))
    report = state.get("structured_report")

    if report is None:
        intent = state.get("intent", "")
        if intent != "strong_stocks":
            errors.append("结构化报告未生成，使用文本模式展示。")
        return {"errors": errors, "current_step": "validate_done"}

    _DIM_ZH = {
        "profitability": "盈利分析",
        "growth": "增长分析",
        "valuation": "估值分析",
        "financial_health": "资产负债",
    }

    for dim_name, fields in _REQUIRED_DIMENSIONS:
        section = report.get(dim_name, {})
        zh = _DIM_ZH.get(dim_name, dim_name)
        if not section:
            errors.append(f"「{zh}」维度数据完全缺失，可能因数据源无返回。")
            continue
        null_fields = [f for f in fields if section.get(f) is None]
        if len(null_fields) == len(fields):
            errors.append(f"「{zh}」所有指标均为空（{', '.join(null_fields)}），数据源可能限流。")
        elif null_fields:
            errors.append(f"「{zh}」部分指标缺失：{', '.join(null_fields)}。")

    io = report.get("intelligence_overview") or {}
    overview = (io.get("summary", "") if isinstance(io, dict) else str(io)).strip()
    highlights = report.get("highlights") or []
    if not overview and not highlights:
        errors.append("综合概述和亮点均未生成。")

    if not report.get("risk_factors"):
        errors.append("未识别到风险因素。")

    # --- Harness: emit validation result to Journal via custom event ---
    validation_errors = [e for e in errors if e not in list(state.get("errors", []))]
    try:
        await adispatch_custom_event("harness_event", {
            "module": "validation",
            "node": "validate_result",
            "missing_dims": validation_errors,
            "total_issues": len(validation_errors),
            "has_structured_report": True,
        })
    except Exception:
        pass

    return {"errors": errors, "current_step": "validate_done"}


# ---------------------------------------------------------------------------
# 6b. Reflection / Self-Critique — LLM judges report quality
# ---------------------------------------------------------------------------

_REFLECT_SYSTEM = """\
你是一位资深投资研究审稿人。请从以下 5 个维度对股票分析报告进行质量评估（0-10 分）：

1. **数据完整性** — 是否覆盖盈利、增长、估值、负债、情绪五大维度
2. **逻辑一致性** — 结论与数据是否一致，有无自相矛盾
3. **风险覆盖** — 是否识别并讨论了关键风险因素
4. **可操作性** — 投资者能否据此报告做出知情决策
5. **表达质量** — 专业性、结构化程度、可读性

请严格输出以下 JSON 格式（不要输出其他内容）：
```json
{
  "score": 7.5,
  "dimensions": {
    "data_completeness": 8,
    "logical_consistency": 7,
    "risk_coverage": 6,
    "actionability": 8,
    "expression_quality": 8
  },
  "feedback": "需要改进的具体建议（中文）"
}
```
"""


# ---------------------------------------------------------------------------
# 6b-i. Deterministic checklist — runs BEFORE LLM-as-Judge
# ---------------------------------------------------------------------------

# Keywords the user might mention → dimension they expect in the report
_USER_DIM_KEYWORDS: list[tuple[list[str], str, list[str]]] = [
    # (user keywords, dimension_label, report_keys_to_check)
    (["债务", "负债", "杠杆", "debt", "leverage"],
     "financial_health", ["debt_to_equity", "current_ratio"]),
    (["估值", "PE", "PB", "市盈", "市净", "valuation"],
     "valuation", ["pe_ratio", "pb_ratio", "ev_to_ebitda"]),
    (["盈利", "利润", "margin", "profit", "毛利", "净利"],
     "profitability", ["gross_margin", "operating_margin", "net_margin", "roe"]),
    (["增长", "growth", "营收增长", "收入增长"],
     "growth", ["revenue_growth_yoy", "earnings_growth_yoy"]),
    (["风险", "risk", "warning"],
     "risk_factors", []),
    (["情绪", "sentiment", "新闻", "news", "舆情"],
     "sentiment", []),
    (["技术", "technical", "K线", "均线", "RSI", "MACD"],
     "technical", []),
]


def _deterministic_checklist(
    user_query: str,
    report: dict[str, Any] | None,
    narrative: str,
) -> tuple[list[str], float]:
    """Check that user-requested dimensions actually appear in the report.

    Returns:
        (missing_items, penalty): list of missing dimension descriptions,
        and a score penalty to subtract from LLM score.
    """
    if not user_query:
        return [], 0.0

    query_lower = user_query.lower()
    report_text_lower = (narrative or json.dumps(report or {}, ensure_ascii=False)).lower()

    missing: list[str] = []
    for keywords, dim_label, report_keys in _USER_DIM_KEYWORDS:
        # Did the user ask about this dimension?
        user_asked = any(kw.lower() in query_lower for kw in keywords)
        if not user_asked:
            continue

        # Is the dimension covered in the report?
        if report and report_keys:
            section = report.get(dim_label, {})
            if isinstance(section, dict):
                has_data = any(section.get(k) is not None for k in report_keys)
            else:
                has_data = bool(section)
        else:
            has_data = dim_label in report_text_lower

        if not has_data:
            missing.append(dim_label)

    penalty = min(len(missing) * 1.5, 4.0)  # cap penalty at 4 points
    return missing, penalty


async def reflect_node(state: AgentState) -> dict[str, Any]:
    """Critic LLM evaluates structured report quality; score < 7 triggers revision.

    Two-phase evaluation:
    1. **Deterministic checklist** — verify user-requested dimensions are present
    2. **LLM-as-Judge** — 5-dimension quality scoring (inferential)
    The deterministic penalty is applied to the LLM score so that missing
    dimensions always trigger revision regardless of LLM leniency.
    """
    report = state.get("structured_report")
    narrative = state.get("analysis_result", {}).get("report", "")

    # Skip reflection for non-analysis intents or missing reports
    if report is None and not narrative:
        return {"reflection_score": 10.0, "current_step": "reflect_skipped"}

    # --- Phase 1: Deterministic checklist ---
    user_query = ""
    msgs = state.get("messages", [])
    for m in msgs:
        if hasattr(m, "type") and m.type == "human":
            user_query = m.content if isinstance(m.content, str) else str(m.content)
            break

    checklist_missing, checklist_penalty = _deterministic_checklist(
        user_query, report, narrative,
    )
    if checklist_missing:
        logger.info(
            "reflect_node: deterministic checklist found %d missing dimensions: %s",
            len(checklist_missing), checklist_missing,
        )

    # --- Phase 2: LLM-as-Judge ---
    report_text = narrative[:3000] if narrative else json.dumps(report, ensure_ascii=False)[:3000]

    from app.llm.factory import get_tool_calling_llm
    llm = get_tool_calling_llm()

    prompt_messages = [
        {"role": "system", "content": _REFLECT_SYSTEM},
        {"role": "user", "content": f"请评估以下分析报告：\n\n{report_text}"},
    ]

    try:
        resp = await llm.ainvoke(prompt_messages)
        raw_text = resp.content or ""

        # Extract JSON from response
        parsed = None
        json_match = re.search(r"```json\s*(.*?)\s*```", raw_text, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(1))
        else:
            # Try bare JSON
            start = raw_text.find("{")
            if start >= 0:
                parsed = json.loads(raw_text[start:])

        if parsed and "score" in parsed:
            llm_score = float(parsed["score"])
            feedback = parsed.get("feedback", "")
            dimensions = parsed.get("dimensions", {})

            # --- Apply deterministic penalty ---
            score = max(0.0, llm_score - checklist_penalty)
            if checklist_missing:
                missing_zh = ", ".join(checklist_missing)
                feedback = (
                    f"[确定性检查] 用户要求的维度缺失：{missing_zh}，"
                    f"扣 {checklist_penalty:.1f} 分。\n{feedback}"
                )

            revision_count = state.get("revision_count", 0)
            logger.info(
                "Reflection llm=%.1f penalty=%.1f final=%.1f revision=%d feedback=%s",
                llm_score, checklist_penalty, score, revision_count, feedback[:80],
            )

            # --- Harness: emit reflection result to Journal via custom event ---
            try:
                await adispatch_custom_event("harness_event", {
                    "module": "reflection",
                    "node": "reflect",
                    "score": score,
                    "llm_score": llm_score,
                    "checklist_penalty": checklist_penalty,
                    "checklist_missing": checklist_missing,
                    "dimensions": dimensions,
                    "feedback": feedback[:300],
                    "revision_count": revision_count,
                    "will_revise": score < 7 and revision_count < 1,
                })
            except Exception:
                pass

            result = {
                "reflection_score": score,
                "reflection_feedback": feedback,
                "current_step": "reflect_done",
            }
            # Pre-set revision_count so the router and synthesis know this is a revision
            if score < 7 and revision_count < 1:
                result["revision_count"] = 1
            return result
    except Exception as exc:
        logger.warning("Reflection LLM call failed (non-fatal): %s", exc)

    # Fallback: if LLM failed but checklist found issues, still trigger revision
    if checklist_penalty >= 2.0:
        missing_zh = ", ".join(checklist_missing)
        fallback_score = max(0.0, 8.0 - checklist_penalty)
        return {
            "reflection_score": fallback_score,
            "reflection_feedback": f"[确定性检查] 用户要求的维度缺失：{missing_zh}",
            "revision_count": 1 if state.get("revision_count", 0) < 1 else state.get("revision_count", 0),
            "current_step": "reflect_done",
        }

    return {"reflection_score": 10.0, "current_step": "reflect_done"}


# ---------------------------------------------------------------------------
# 7. Render output — structured report → deterministic Markdown
# ---------------------------------------------------------------------------

def _fmt_pct(v: Any) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v) * 100:.1f}%" if abs(float(v)) < 1 else f"{float(v):.1f}%"
    except (TypeError, ValueError):
        return str(v)


def _fmt_num(v: Any) -> str:
    if v is None:
        return "N/A"
    try:
        f = float(v)
        if abs(f) >= 1e12:
            return f"${f/1e12:.2f}T"
        if abs(f) >= 1e9:
            return f"${f/1e9:.2f}B"
        if abs(f) >= 1e6:
            return f"${f/1e6:.1f}M"
        return f"{f:.2f}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_ratio(v: Any) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)


async def render_output_node(state: AgentState) -> dict[str, Any]:
    """Merge synthesis narrative with deterministic metric tables.

    Strategy:
    - **Primary body**: synthesis narrative from ``analysis_result.report``
      (rich context produced by the reasoning LLM).
    - **Appendix**: structured metric tables rendered deterministically from
      ``structured_report`` JSON for quick reference.
    - When ``structured_report`` is None, fall back to the narrative only.

    This avoids the old duplication where synthesis narrative was discarded and
    the same data was re-rendered from JSON into a less-rich template.
    """
    report = state.get("structured_report")
    synthesis_narrative = state.get("analysis_result", {}).get("report", "")
    errors = state.get("errors", [])

    # --- No structured report: use synthesis narrative directly ---
    if report is None:
        md = synthesis_narrative
        if errors:
            md += "\n\n---\n**Data Limitations**\n" + "\n".join(f"- {e}" for e in errors)
        return {
            "markdown_report": md,
            "current_step": "render_done",
            "messages": [AIMessage(content=md)],
        }

    # --- Structured report exists: narrative + metric appendix ---
    ticker = report.get("ticker", "")
    name = report.get("company_name", ticker)
    industry = report.get("industry", "")
    price = report.get("current_price")

    prof = report.get("profitability", {})
    growth = report.get("growth", {})
    val = report.get("valuation", {})
    health = report.get("financial_health", {})
    sent = report.get("news_sentiment", {})
    risks = report.get("risk_factors", [])
    highlights = report.get("highlights", [])

    # Build the primary section from synthesis narrative
    header = (
        f"# {name} ({ticker}) 情报简报\n\n"
        f"**行业:** {industry or 'N/A'}  |  **价格:** {_fmt_num(price) if price else 'N/A'}\n\n"
        "_以下内容仅供信息参考，不构成投资建议。_\n"
    )

    # Use the synthesis narrative as the main body; fall back to overview if empty
    body = synthesis_narrative.strip()
    if not body:
        overview = (report.get("intelligence_overview") or {}).get("summary", "")
        body = overview or "_综合分析叙述未生成。_"

    # Append deterministic metric tables as a quick-reference appendix
    appendix_lines = [
        "",
        "---",
        "",
        "## 📊 关键指标速查",
        "",
        "### 盈利能力",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 毛利率 | {_fmt_pct(prof.get('gross_margin'))} |",
        f"| 营业利润率 | {_fmt_pct(prof.get('operating_margin'))} |",
        f"| 净利率 | {_fmt_pct(prof.get('net_margin'))} |",
        f"| ROE | {_fmt_pct(prof.get('roe'))} |",
        f"| ROA | {_fmt_pct(prof.get('roa'))} |",
        "",
        "### 成长性",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 营收增长 (YoY) | {_fmt_pct(growth.get('revenue_growth_yoy'))} |",
        f"| 盈利增长 (YoY) | {_fmt_pct(growth.get('earnings_growth_yoy'))} |",
        f"| 营收 CAGR (3Y) | {_fmt_pct(growth.get('revenue_cagr_3y'))} |",
        "",
        "### 估值",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| P/E | {_fmt_ratio(val.get('pe_ratio'))} |",
        f"| P/B | {_fmt_ratio(val.get('pb_ratio'))} |",
        f"| P/S | {_fmt_ratio(val.get('ps_ratio'))} |",
        f"| EV/EBITDA | {_fmt_ratio(val.get('ev_to_ebitda'))} |",
        f"| PEG | {_fmt_ratio(val.get('peg_ratio'))} |",
        "",
        "### 财务健康",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 负债/权益 | {_fmt_ratio(health.get('debt_to_equity'))} |",
        f"| 流动比率 | {_fmt_ratio(health.get('current_ratio'))} |",
        f"| 速动比率 | {_fmt_ratio(health.get('quick_ratio'))} |",
        f"| 自由现金流 | {_fmt_num(health.get('free_cash_flow'))} |",
        "",
        "### 舆情",
        f"**综合评价:** {sent.get('overall', 'N/A')}",
        "",
    ]

    if highlights:
        appendix_lines.append("### 核心亮点")
        for h in highlights:
            appendix_lines.append(f"- {h}")
        appendix_lines.append("")

    if risks:
        appendix_lines.append("### 风险因素")
        for r in risks:
            appendix_lines.append(f"- {r}")
        appendix_lines.append("")

    if errors:
        appendix_lines.append("---")
        appendix_lines.append("**数据限制**")
        for e in errors:
            appendix_lines.append(f"- {e}")
        appendix_lines.append("")

    md = header + "\n" + body + "\n".join(appendix_lines)

    return {
        "markdown_report": md,
        "current_step": "render_done",
        "messages": [AIMessage(content=md)],
    }


# ---------------------------------------------------------------------------
# 7b. Multi-Intent Queue — advance to next intent
# ---------------------------------------------------------------------------


async def advance_queue_node(state: AgentState) -> dict[str, Any]:
    """Pop the next intent from ``intent_queue`` and set it as active.

    - If more items remain → write ``intent``, ``tickers``, ``screening_params``
      from the next queue item and set ``current_step = "queue_next"``.
    - If queue is exhausted → ``current_step = "queue_done"``.

    Also collects a one-line summary of the just-finished intent into
    ``intent_results`` for final aggregation.
    """
    queue = list(state.get("intent_queue") or [])
    idx = state.get("intent_queue_index", 0)
    results = list(state.get("intent_results") or [])

    # Record a summary of the completed intent
    finished = queue[idx] if idx < len(queue) else None
    if finished:
        summary = f"{finished['intent']}({','.join(finished.get('tickers', []))}) ✓"
        results.append(summary)

    # ── Emit intent_done event so frontend streams intermediate results ────
    # Extract the last AIMessage produced by the just-completed sub-flow.
    if finished and len(queue) > 1:
        last_ai_content = ""
        for m in reversed(state.get("messages", [])):
            if isinstance(m, AIMessage) and m.content:
                last_ai_content = m.content
                break
        if last_ai_content:
            try:
                await adispatch_custom_event("intent_done", {
                    "intent": finished["intent"],
                    "tickers": finished.get("tickers", []),
                    "index": idx,
                    "total": len(queue),
                    "content": last_ai_content,
                })
            except Exception:
                pass

    next_idx = idx + 1
    if next_idx < len(queue):
        nxt = queue[next_idx]
        intent = nxt["intent"]
        tickers = nxt.get("tickers", [])

        # Multi-ticker single_stock → compare
        if intent == "single_stock" and len(tickers) > 1:
            intent = "compare"
            nxt["intent"] = "compare"

        logger.info(
            "advance_queue: advancing %d→%d, next intent=%s tickers=%s",
            idx, next_idx, intent, tickers,
        )

        # Emit SSE event for analysis intents
        if intent in ("single_stock", "compare") and tickers:
            await adispatch_custom_event("ticker_select", {"ticker": tickers[0], "intent": intent})

        result: dict[str, Any] = {
            "intent": intent,
            "tickers": tickers,
            "intent_queue_index": next_idx,
            "intent_results": results,
            "current_step": "queue_next",
            "errors": [],
        }
        sp = nxt.get("screening_params", {})
        if sp:
            result["screening_params"] = sp
        return result

    # Queue exhausted
    logger.info("advance_queue: queue exhausted (%d items completed)", len(queue))
    return {
        "intent_queue_index": next_idx,
        "intent_results": results,
        "current_step": "queue_done",
    }


# ---------------------------------------------------------------------------
# 8. Chat orchestrator node — intent dispatch + context-aware conversation
# ---------------------------------------------------------------------------

_ANALYSIS_CONTEXT_MAX_CHARS = 6000  # Hard cap to prevent blowing up system_prompt


def _build_analysis_context(state: AgentState) -> str:
    """Extract prior analysis data from state for follow-up context injection.

    Returns a formatted string summarising the structured report and raw
    financial data, or ``""`` if no prior analysis exists.  Output is capped
    at ``_ANALYSIS_CONTEXT_MAX_CHARS`` characters.
    """
    report = state.get("structured_report")
    fin_data = state.get("financial_data") or {}
    symbol = state.get("resolved_symbol", "")

    if not report and not fin_data:
        return ""

    parts: list[str] = []
    if symbol:
        parts.append(f"## 当前分析标的: {symbol}")

    if report and isinstance(report, dict):
        parts.append("### 结构化分析摘要 (structured_report)")

        io = report.get("intelligence_overview") or {}
        summary = io.get("summary", "") if isinstance(io, dict) else str(io)
        if summary:
            parts.append(f"**综合概述**: {summary}")

        _DIM_LABELS = {
            "profitability": "盈利分析",
            "growth": "增长分析",
            "valuation": "估值分析",
            "financial_health": "资产负债",
            "news_sentiment": "舆情分析",
        }
        for dim_key, dim_label in _DIM_LABELS.items():
            section = report.get(dim_key)
            if section and isinstance(section, dict):
                items = [f"{k}={v}" for k, v in section.items()
                         if v is not None and k != "summary"]
                s = section.get("summary", "")
                line = f"**{dim_label}**: {', '.join(items)}"
                if s:
                    line += f" | {s[:200]}"
                parts.append(line)

        highlights = report.get("highlights") or []
        if highlights:
            parts.append("**亮点**: " + "; ".join(highlights[:5]))

        risks = report.get("risk_factors") or []
        if risks:
            parts.append("**风险因素**: " + "; ".join(risks[:5]))

    # Include truncated raw data for deeper context
    for key, label in [("fundamental_text", "原始基本面数据"),
                       ("sentiment_text", "原始舆情数据")]:
        raw = fin_data.get(key, "")
        if raw:
            parts.append(f"\n### {label}\n{str(raw)[:2000]}")

    result = "\n".join(parts) if parts else ""
    if len(result) > _ANALYSIS_CONTEXT_MAX_CHARS:
        result = result[:_ANALYSIS_CONTEXT_MAX_CHARS] + "\n…[已截断]"
    return result


_CHAT_SYSTEM_BASE = """\
You are Atlas, a financial intelligence assistant backed by real-time data tools.

CRITICAL RULES — follow these unconditionally:
1. NEVER answer questions about stock prices, financial metrics, earnings, market data, \
screening results, or any other financial figures from your own training knowledge.
2. For ANY finance-related question, you MUST call the appropriate tool first — \
UNLESS prior analysis context is provided below. If prior context contains the data, \
answer directly from it. Only call tools when the context is insufficient.
3. If neither tools nor context return relevant data, respond clearly: \
"暂无相关数据，无法回答此问题。" (or in user's language).
4. You MAY answer general, non-finance questions (greetings, how-to usage, etc.) directly.
5. Never fabricate prices, metrics, or fundamentals.
6. When answering from prior context, cite "📊 基于已有分析数据"; when from tools, cite tool names.
7. **Coreference resolution**: When the user uses pronouns like "它", "这个", "那只", "this", "it", \
always resolve them from the conversation history. Look at the most recent ticker / stock mentioned \
in prior messages and use that as the target. Never ask "which stock?" if the context is clear.

## Tool Reference — choose based on the user's intent

### 基本面 / 公司分析
- get_company_profile — 公司概况（行业、市值、简介）。场景：用户问"XX是做什么的"、"XX属于什么行业"。
- get_financial_statements — 财务报表（利润表/资产负债表/现金流）。场景：用户问营收、净利润、负债、自由现金流等。
- get_key_metrics — 核心估值与财务指标（PE/PB/ROE/EPS 等）。场景：用户问"XX的PE是多少"、"估值高不高"。
- get_risk_metrics — 风险指标（Beta、波动率、做空比例、内部人交易）。场景：用户问风险、波动、做空情况。
- get_catalysts — 催化剂事件（财报日、除息日等）。场景：用户问"什么时候财报"、"有没有即将除息"。
- get_peer_comparison — 同业对比（PE/ROE/利润率/市值横向比较）。场景：用户问"和同行比怎么样"、"行业对比"。

### 行情 / 价格
- get_price_history — 历史 K 线/OHLCV。场景：用户问"最近走势"、"过去半年价格"、"给我 K 线数据"。
- get_technical_analysis — 单股技术分析（RSI/MACD/布林带/低波动/突破信号）。场景：用户问"技术面怎么样"、"RSI多少"、"有没有突破信号"、"波动率"。

### 舆情
- get_company_news — 近期新闻。场景：用户问"XX最近有什么新闻"、"利好利空"。

### 市场 / 监控
- get_strong_stocks — 强势股筛选（按动量评分排名）。场景：用户问"最近有什么强势股"、"美股/港股哪些涨得好"。
- get_market_overview — 大盘行情与市场状态。场景：用户问"今天大盘怎么样"、"市场状况"。
- get_monitoring_alerts — 监控池扫描告警（低波动/突破信号批量扫描）。场景：用户问"有没有低波动信号"、"监控池有什么提醒"、"哪些股票出现突破"。注意：此工具耗时较长。

### 标的解析（MUST-USE）
- resolve_symbol — 将模糊输入解析为精确标的代码。输入可以是中文名("英伟达")、数字("1428")、英文名("Nike")。
  ⚠️ **规则：任何需要 ticker 的操作（加观察组、删观察组、建任务等），若用户给的不是明确的标准代码，必须先调 resolve_symbol 拿到真实 ticker 后再调后续 tool。**
  流程示例：用户说"将1428加入观察组" → 先 resolve_symbol("1428") 拿到 "1428.HK" → 再 add_to_watchlist("1428.HK")

### 用户数据 / 观察组
- get_watchlist — 查询用户观察组。
- add_to_watchlist — 加入观察组（需先 resolve_symbol）。
- remove_from_watchlist — 移出观察组。
- clear_watchlist — 清空观察组。

### 任务管理
- create_task — 创建自动分析任务（需先 resolve_symbol 解析标的列表）。
- list_tasks — 查询用户任务列表。
- delete_task — 删除指定任务。

### 记忆管理
- list_memories — 查询用户长期记忆。
- delete_memory — 删除指定记忆。
- clear_memories — 清空所有记忆。

### 组合调用建议
- "帮我分析XX" → get_company_profile + get_key_metrics + get_technical_analysis
- "XX值不值得买" → get_key_metrics + get_peer_comparison + get_risk_metrics + get_technical_analysis
- "有什么机会" → get_strong_stocks 或 get_monitoring_alerts
- "XX技术面" → get_technical_analysis（若需价格细节再加 get_price_history）
- "将XX加入观察组" → resolve_symbol(XX) → add_to_watchlist(resolved_ticker)

Respond in the same language as the user."""

_CHAT_MAX_TOOL_ROUNDS = 5

_TOOL_LABELS: dict[str, str] = {
    "get_financial_statements": "财务报表",
    "get_key_metrics": "核心指标",
    "get_company_profile": "公司概况",
    "get_company_news": "新闻舆情",
    "get_peer_comparison": "同业对比",
    "get_risk_metrics": "风险指标",
    "get_catalysts": "催化剂事件",
    "get_strong_stocks": "强势股筛选",
    "get_market_overview": "市场行情",
    "get_price_history": "历史价格",
    "get_watchlist": "观察组",
    "get_technical_analysis": "技术分析",
    "get_monitoring_alerts": "监控告警",
    "resolve_symbol": "标的解析",
    "add_to_watchlist": "加入观察组",
    "remove_from_watchlist": "移出观察组",
    "clear_watchlist": "清空观察组",
    "create_task": "创建任务",
    "list_tasks": "任务列表",
    "delete_task": "删除任务",
    "list_memories": "记忆查询",
    "delete_memory": "删除记忆",
    "clear_memories": "清空记忆",
}


_CHAT_ORCHESTRATOR_SYSTEM = """\
You are the orchestration layer of Atlas, a financial intelligence system.
Your ONLY job is to decide whether the user's message should be handled by a specialised agent or answered conversationally.

## Decision rules
1. If the user is asking for a **fundamental analysis / research** of a specific stock → output intent "single_stock" with tickers.
2. If the user wants to **compare** multiple stocks → "compare" with tickers.
3. If the user wants to **screen / list strong stocks** or **change screening params** → "update_config" with screening_params.
4. If the request needs **multiple sequential steps** → "multi_step" with tickers.
5. **Everything else** → "chat". This includes:
   - Greetings, usage questions, general questions
   - Follow-up questions on existing analysis
   - **Watchlist management** (add/remove from watchlist) — the chat node has tools for this.
     Examples: "把NKE加入观察组", "将1428加自选", "NKE加观察" → intent="chat"

## HARD RULE — analysis keyword + stock = single_stock
If the message contains any analysis keyword (分析/基本面/研究/看看…财务/估值/analyze/research/fundamental)
AND mentions a specific stock name or ticker → intent MUST be "single_stock" (or "compare" if multiple).
Do NOT classify these as "chat". Examples: "分析苹果", "AAPL基本面", "帮我研究英伟达".

## EXCEPTION — follow-ups on existing analysis → chat
If the conversation ALREADY contains a completed analysis for the SAME stock, and the user
asks a follow-up ("这个PE高吗", "债务情况怎么样") WITHOUT re-requesting analysis → "chat".

## Coreference resolution
When the user uses pronouns like "它", "这个", "那只", "this", "it", resolve them from conversation history.
Look at the most recent ticker/stock in prior messages and use that. Never leave tickers empty if context is clear.
Example: prior message mentioned 0175.HK, user says "帮我分析一下它" → intent=single_stock, tickers=["0175.HK"]

Output ONLY a raw JSON object:
{"intent": "...", "tickers": [...], "screening_params": {"market_type": "...", "top_count": N, ...}}
Include screening_params only when intent is "update_config". Include tickers only when relevant.
Map names: 英伟达→NVDA, 苹果→AAPL, 特斯拉→TSLA, 腾讯→0700.HK, 谷歌→GOOGL"""


async def chat_node(state: AgentState) -> dict[str, Any]:
    """Orchestrator + context-aware chat node.

    Phase 0 — **Queue-driven simple intent**: If the intent_queue routed us here
              with a simple intent (watchlist_add/remove), execute it directly via
              tool call and return — no LLM intent detection needed.
    Phase 1 — **Intent detection**: Use LLM to check if the user's message implies
              an actionable intent (analysis, config, watchlist). If so, update state
              and return immediately; the graph's conditional edge dispatches.
    Phase 2 — **Context-aware conversation**: Inject prior analysis data from state
              (structured_report, financial_data) into the LLM context so follow-up
              questions can be answered without redundant tool calls. Tools are still
              available for supplementation when context is insufficient.
    """
    import asyncio as _aio
    from langchain_core.messages import ToolMessage
    from app.tools import ALL_TOOLS

    messages = state["messages"]
    last_human = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            last_human = m.content
            break

    # ── Phase 0: Queue-driven simple intent (no LLM needed) ───────────────
    queue = state.get("intent_queue") or []
    q_idx = state.get("intent_queue_index", 0)
    current_intent = state.get("intent", "chat")
    is_queue_driven = (
        state.get("current_step") == "queue_next"
        or (len(queue) > 1 and current_intent in ("watchlist_add", "watchlist_remove", "chat")
            and q_idx < len(queue))
    )

    # Watchlist add/remove always uses Phase 0 fast path (no LLM needed),
    # regardless of queue length — ensures watchlist_update SSE is emitted.
    if current_intent in ("watchlist_add", "watchlist_remove"):
        q_item = queue[q_idx] if q_idx < len(queue) else {}
        q_tickers = q_item.get("tickers", []) or list(state.get("tickers") or [])
        tool_name = "add_to_watchlist" if current_intent == "watchlist_add" else "remove_from_watchlist"
        results_msgs: list[Any] = []
        success_tickers: list[str] = []

        for ticker in q_tickers:
            # Resolve symbol first if needed
            try:
                from app.tools.symbol_resolver import resolve_symbol
                resolved = await _aio.to_thread(resolve_symbol.invoke, {"query": ticker})
                resolved_data = json.loads(resolved)
                final_ticker = resolved_data.get("symbol", ticker)
            except Exception:
                final_ticker = ticker

            tool_map = {t.name: t for t in ALL_TOOLS}
            tool = tool_map.get(tool_name)
            if tool:
                try:
                    result_str = await _aio.to_thread(tool.invoke, {"ticker": final_ticker})
                    action_label = "加入" if current_intent == "watchlist_add" else "移出"
                    results_msgs.append(f"✅ **{final_ticker}** 已{action_label}观察组")
                    success_tickers.append(final_ticker)
                    logger.info("chat_node: queue-driven %s(%s) OK", tool_name, final_ticker)
                except Exception as exc:
                    results_msgs.append(f"⚠️ {tool_name}({final_ticker}) 失败: {exc}")
                    logger.warning("chat_node: queue-driven %s(%s) failed: %s", tool_name, final_ticker, exc)

        # Emit watchlist_update SSE so frontend syncs candidate card buttons
        if success_tickers:
            action = "add" if current_intent == "watchlist_add" else "remove"
            try:
                await adispatch_custom_event("watchlist_update", {
                    "tickers": success_tickers,
                    "action": action,
                })
            except Exception:
                pass

        content = "\n".join(results_msgs) if results_msgs else f"⚠️ {current_intent}: 无标的"
        out: dict[str, Any] = {
            "current_step": "chat_done",
            "messages": [AIMessage(content=content)],
        }
        if success_tickers:
            out["watchlist_update"] = success_tickers
        return out

    # ── Phase 1: Intent detection via LLM ──────────────────────────────────
    # Skip if queue is driving us (current_step == "queue_next" with a chat intent)
    if is_queue_driven:
        # Queue routed us to chat — skip intent detection, go straight to Phase 2
        logger.info("chat_node: queue-driven chat, skipping Phase 1")
        detected_intent = "chat"
        detected_tickers: list[str] = []
        detected_sp: dict[str, Any] = {}
    else:
        llm = get_tool_calling_llm()
        context_msgs: list[dict[str, str]] = [
            {"role": "system", "content": _CHAT_ORCHESTRATOR_SYSTEM},
        ]
        recent = messages[-(min(len(messages), 7)):-1] if len(messages) > 1 else []
        for m in recent:
            if isinstance(m, HumanMessage):
                context_msgs.append({"role": "user", "content": m.content[:200]})
            elif isinstance(m, AIMessage) and m.content:
                context_msgs.append({"role": "assistant", "content": m.content[:200]})
        context_msgs.append({"role": "user", "content": last_human})

        detected_intent = "chat"
        detected_tickers = []
        detected_sp = {}

        try:
            resp = await llm.ainvoke(context_msgs, config={"tags": ["internal"]})
            raw = resp.content.strip()
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw.strip())
            idx = raw.find("{")
            if idx >= 0:
                obj, _ = json.JSONDecoder().raw_decode(raw, idx)
                parsed = _IntentOutput.model_validate(obj)
                # Use legacy single-intent field for chat_node detection
                detected_intent = parsed.intent or "chat"
                detected_tickers = [t for t in parsed.tickers if t]
                detected_sp = {k: v for k, v in parsed.screening_params.model_dump().items() if v is not None}
                if detected_intent == "strong_stocks":
                    detected_intent = "update_config"
        except Exception as exc:
            logger.warning("chat_node: intent detection failed (%s), falling back to conversation", exc)

        logger.info("chat_node: detected intent=%s tickers=%s", detected_intent, detected_tickers)

        # ── Dispatch if actionable intent detected ─────────────────────────
        if detected_intent != "chat":
            result: dict[str, Any] = {
                "intent": detected_intent,
                "tickers": detected_tickers,
                "current_step": "chat_dispatched",
                "errors": [],
            }
            if detected_sp:
                result["screening_params"] = detected_sp
            if detected_intent in ("single_stock", "compare") and detected_tickers:
                await adispatch_custom_event("ticker_select", {"ticker": detected_tickers[0], "intent": detected_intent})
            if detected_intent in ("single_stock",) and len(detected_tickers) > 1:
                await adispatch_custom_event("multi_analyze", {"tickers": detected_tickers, "original_intent": detected_intent})
                result["intent"] = "compare"
            logger.info("chat_node: dispatching to intent=%s", result["intent"])
            return result

        # ── Fallback: LLM said "chat" but message has analysis keywords + tickers ──
        if detected_intent == "chat" and detected_tickers and _ANALYZE_KW_RE.search(last_human):
            logger.info("chat_node: FALLBACK override chat→single_stock (tickers=%s, keywords matched)", detected_tickers)
            override_intent = "compare" if len(detected_tickers) > 1 else "single_stock"
            await adispatch_custom_event("ticker_select", {"ticker": detected_tickers[0], "intent": override_intent})
            if len(detected_tickers) > 1:
                await adispatch_custom_event("multi_analyze", {"tickers": detected_tickers, "original_intent": override_intent})
                override_intent = "compare"
            return {
                "intent": override_intent,
                "tickers": detected_tickers,
                "current_step": "chat_dispatched",
                "errors": [],
            }

    # ── Phase 2: Context-aware conversation ────────────────────────────────
    analysis_ctx = _build_analysis_context(state)

    # ── Token budget management (initialise early so we can trim) ──────────
    budget_data = state.get("token_budget")
    if budget_data:
        budget = TokenBudgetManager.from_dict(budget_data)
    else:
        settings = get_settings()
        budget = TokenBudgetManager(model_limit=settings.harness_model_context_limit)

    system_prompt = augment_system_prompt(_CHAT_SYSTEM_BASE)
    budget.record("system_prompt", system_prompt)

    # ── Analysis context: trim to budget before appending ──────────────────
    if analysis_ctx:
        analysis_ctx = budget.trim_to_budget("rag_context", analysis_ctx)
        if analysis_ctx:
            system_prompt += (
                "\n\n---\n## 已有分析数据（Prior Analysis Context）\n"
                "以下是之前 Agent 产出的分析结果，优先使用这些数据回答用户追问，"
                "数据不够时再调用工具补充。\n\n" + analysis_ctx
            )
            budget.record("rag_context", analysis_ctx)

    # ── Long-term memory: inject user context (separate budget category) ──
    user_id = state.get("user_id", "")
    ltm_context = ""
    if user_id:
        try:
            from app.harness.long_term_memory import LongTermMemory
            ltm = await LongTermMemory.create()
            ltm_context = await ltm.get_user_context(user_id, max_entries=10)
            await ltm.close()
        except Exception as exc:
            logger.warning("chat_node: LTM read failed: %s", exc)
    if ltm_context:
        ltm_context = budget.trim_to_budget("long_term_memory", ltm_context)
        if ltm_context:
            system_prompt += (
                "\n\n---\n## 用户历史记忆（Long-term Memory）\n"
                "以下是该用户的历史偏好和分析记录，用于个性化回复。\n\n"
                + ltm_context
            )
            budget.record("long_term_memory", ltm_context)

    # Rebalance: redistribute unused budget (e.g. no RAG in chat mode)
    budget.rebalance()

    # ── Compaction: compress older messages if budget is tight ──────────────
    compacted_messages = await compact_conversation(messages, budget)
    if len(compacted_messages) < len(messages):
        logger.info("chat_node: compacted %d → %d messages", len(messages), len(compacted_messages))
        try:
            await adispatch_custom_event("harness_event", {
                "module": "compaction",
                "before_messages": len(messages),
                "after_messages": len(compacted_messages),
                "usage_ratio": round(budget.usage_ratio(), 2),
            })
        except Exception:
            pass

    # --- Harness: per-run rate limiter (NOT a process-level singleton) ---
    from app.harness.rate_limiter import ToolRateLimiter
    chat_node._run_rate_limiter = ToolRateLimiter()  # type: ignore[attr-defined]

    llm_with_tools = get_tool_calling_llm().bind_tools(ALL_TOOLS)
    tool_map = {t.name: t for t in ALL_TOOLS}

    history = [
        {"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": m.content}
        for m in compacted_messages
        if hasattr(m, "content") and m.content
    ]

    # Record conversation token usage
    conv_text = " ".join(h["content"] for h in history if h.get("content"))
    budget.record("conversation", conv_text)
    budget.log_summary()

    loop_messages: list[Any] = [
        {"role": "system", "content": system_prompt},
        *history,
    ]

    called_tools: list[str] = []
    used_context = bool(analysis_ctx)

    def _make_return(content: str, step: str = "chat_done") -> dict[str, Any]:
        """Build return dict with budget state persisted."""
        return {
            "current_step": step,
            "messages": [AIMessage(content=content)],
            "token_budget": budget.to_dict(),
        }

    for round_idx in range(_CHAT_MAX_TOOL_ROUNDS + 1):
        try:
            resp = await llm_with_tools.ainvoke(loop_messages)
        except Exception as exc:
            is_retryable = "529" in str(exc) or "overloaded" in str(exc).lower() or "null value for 'choices'" in str(exc)
            if is_retryable:
                logger.warning("chat_node LLM call failed (retryable): %s", exc)
                await _aio.sleep(2)
                continue
            raise

        tool_calls = getattr(resp, "tool_calls", []) or []

        if not tool_calls:
            content = resp.content or ""
            source_parts: list[str] = []
            if used_context and not called_tools:
                source_parts.append("📊 **已有分析数据**")
            if called_tools:
                unique = list(dict.fromkeys(called_tools))
                tags = " · ".join(f"**{_TOOL_LABELS.get(t, t)}**" for t in unique)
                source_parts.append(tags)
            if source_parts:
                sources_line = "📡 数据来源 — " + " + ".join(source_parts)
                content = sources_line + "\n\n" + content

            # ── Long-term memory: extract preferences (fire-and-forget) ────
            if user_id and history:
                user_msg = next((h["content"] for h in reversed(history) if h["role"] == "user"), "")
                if user_msg:
                    asyncio.create_task(_extract_and_save_preferences(user_id, user_msg, content))

            return _make_return(content)

        if round_idx == _CHAT_MAX_TOOL_ROUNDS:
            logger.warning("chat_node: exceeded max tool rounds, returning partial response")
            return _make_return(resp.content or "⚠️ 数据获取超限，请简化问题后重试。")

        loop_messages.append(resp)
        for tc in tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]

            # --- Harness: permission guard ---
            from app.harness.permissions import get_permission_guard
            guard = get_permission_guard()
            if not guard.check_allowed(tool_name):
                result_str = f"Tool '{tool_name}' blocked by permission guard (tier={guard.get_tier(tool_name).value})"
                logger.warning("chat_node: %s", result_str)
                loop_messages.append(
                    ToolMessage(content=result_str, tool_call_id=tc["id"])
                )
                continue

            # --- Harness: rate limiter (per-run instance) ---
            if not chat_node._run_rate_limiter.allow(tool_name):  # type: ignore[attr-defined]
                result_str = f"Tool '{tool_name}' rate-limited — too many calls this run"
                logger.warning("chat_node: %s", result_str)
                loop_messages.append(
                    ToolMessage(content=result_str, tool_call_id=tc["id"])
                )
                continue

            called_tools.append(tool_name)
            logger.info("chat_node: calling tool %s(%s)", tool_name, tool_args)
            tool = tool_map.get(tool_name)
            if tool is None:
                result_str = f"Tool '{tool_name}' not found."
            else:
                try:
                    result_str = await asyncio.to_thread(tool.invoke, tool_args)
                except Exception as exc:
                    result_str = f"Tool error: {exc}"

            # --- Harness: emit tool call event to Journal ---
            try:
                await adispatch_custom_event("harness_event", {
                    "module": "tool_call",
                    "node": "chat",
                    "tool": tool_name,
                    "args_keys": list(tool_args.keys()) if isinstance(tool_args, dict) else [],
                    "result_chars": len(str(result_str)),
                    "round": round_idx,
                })
            except Exception:
                pass

            budget.record("tool_results", str(result_str))
            loop_messages.append(
                ToolMessage(content=str(result_str), tool_call_id=tc["id"])
            )

    logger.error("chat_node: exhausted all rounds without final response")
    return _make_return("⚠️ AI 服务暂时不可用，请稍后重试。")


# ---------------------------------------------------------------------------
# Harness: Approval Gate (Phase 6 — Risk Approval)
# ---------------------------------------------------------------------------


async def approval_gate_node(state: AgentState) -> dict[str, Any]:
    """Check whether the pending action requires human approval.

    Currently evaluates the ``intent`` to decide:
    - Future ``trade_*`` intents → would interrupt for approval (high risk)

    This node is transparent for all current intents — it passes through
    without blocking.  The infrastructure is in place for future write-tier
    operations to trigger ``interrupt()`` for human confirmation.
    """
    from app.harness.permissions import get_permission_guard, ToolTier

    intent = state.get("intent", "")
    tickers = state.get("tickers", [])
    guard = get_permission_guard()

    # Map intent to a virtual tool name for permission checking
    _INTENT_TOOL_MAP: dict[str, str] = {}

    virtual_tool = _INTENT_TOOL_MAP.get(intent, "")
    if virtual_tool:
        entry = guard.check_and_log(virtual_tool)
        logger.info(
            "approval_gate: intent=%s tickers=%s tier=%s allowed=%s",
            intent, tickers, entry["tier"], entry["allowed"],
        )
        if not entry["allowed"]:
            # High-risk: would need interrupt() here for human confirmation
            # For now, all current write operations are medium-risk → auto-approve
            logger.warning(
                "approval_gate: action requires approval but auto-approving (no high-risk ops yet)"
            )

    return {
        "current_step": "approval_passed",
    }


# ---------------------------------------------------------------------------
# Harness: Long-term Memory — preference extraction
# ---------------------------------------------------------------------------

_PREFERENCE_EXTRACTION_PROMPT = """\
从以下用户与助手的对话中，提取用户的投资偏好。
仅提取用户**明确表达**的偏好，不要推测。如果没有发现偏好，返回空 JSON `{}`。

返回 JSON 格式（仅包含检测到的字段）：
{
  "market": "偏好的市场（如美股、港股、A股）",
  "sector": "偏好的行业/板块",
  "style": "投资风格（如价值投资、成长股、趋势跟踪）",
  "risk": "风险偏好（如保守、稳健、激进）",
  "other": "其他明确偏好"
}

用户消息：{user_msg}
助手回复：{assistant_msg}
"""


async def _extract_and_save_preferences(user_id: str, user_msg: str, assistant_msg: str) -> None:
    """Use a lightweight LLM call to extract user preferences and save to LTM."""
    try:
        from app.llm.factory import create_llm
        from app.harness.long_term_memory import LongTermMemory

        llm = create_llm(role="reasoning", temperature=0.0, max_tokens=256)
        prompt = _PREFERENCE_EXTRACTION_PROMPT.format(
            user_msg=user_msg[:500],
            assistant_msg=assistant_msg[:500],
        )
        resp = await llm.ainvoke([{"role": "user", "content": prompt}])
        raw = (resp.content or "").strip()

        # Parse JSON from response
        idx = raw.find("{")
        if idx < 0:
            return
        obj, _ = json.JSONDecoder().raw_decode(raw, idx)
        if not obj or not isinstance(obj, dict):
            return

        # Filter out empty values
        prefs = {k: v for k, v in obj.items() if v and v.strip()}
        if not prefs:
            return

        ltm = await LongTermMemory.create()
        for key, value in prefs.items():
            await ltm.remember(user_id, "preference", key, value)
        await ltm.close()
        logger.debug("LTM: saved %d preference(s) for user %s", len(prefs), user_id)
    except Exception as exc:
        logger.warning("LTM: preference extraction failed: %s", exc)
