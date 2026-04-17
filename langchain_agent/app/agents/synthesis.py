"""Synthesis node — combines gathered data into structured intelligence + markdown."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.config import get_settings
from app.harness.resident_product import normalize_user_error
from app.llm.factory import get_reasoning_llm
from app.models.analysis import FundamentalReport
from app.prompts.response_policy import augment_system_prompt
from app.prompts.synthesis import SYNTHESIS_SYSTEM

logger = logging.getLogger(__name__)

_STRUCTURED_ADDENDUM = """

IMPORTANT: After your analysis, output a JSON block fenced with ```json ... ```
that conforms to this schema (all numeric fields are floats or null):

{
  "ticker": "AAPL",
  "company_name": "Apple Inc.",
  "industry": "Consumer Electronics",
  "current_price": 195.0,
  "profitability": {
    "gross_margin": 0.45, "operating_margin": 0.30, "net_margin": 0.25,
    "roe": 1.47, "roa": 0.28, "summary": "..."
  },
  "growth": {
    "revenue_growth_yoy": 0.08, "earnings_growth_yoy": 0.12,
    "revenue_cagr_3y": 0.10, "summary": "..."
  },
  "valuation": {
    "pe_ratio": 32.0, "pb_ratio": 48.0, "ps_ratio": 8.5,
    "ev_to_ebitda": 26.0, "peg_ratio": 2.8, "summary": "..."
  },
  "financial_health": {
    "debt_to_equity": 1.8, "current_ratio": 1.0, "quick_ratio": 0.9,
    "free_cash_flow": 100000000000, "summary": "..."
  },
  "news_sentiment": {
    "overall": "positive", "positive_count": 5, "negative_count": 1,
    "neutral_count": 2, "key_headlines": ["..."], "summary": "..."
  },
  "intelligence_overview": {
    "summary": "2-5 sentences: factual synthesis only; no buy/sell/hold unless user explicitly asked for advice."
  },
  "risk_factors": ["...", "..."],
  "highlights": ["...", "..."]
}

Use null for any metric you don't have data for. The JSON block MUST be valid.
"""

_JSON_LOCALE_ZH_NOTE = """
When producing the JSON block: every human-readable string field (summaries, highlights,
risk_factors text, headlines, etc.) MUST be in Simplified Chinese.
"""


def _structured_addendum() -> str:
    tail = _JSON_LOCALE_ZH_NOTE if get_settings().atlas_force_response_locale == "zh" else ""
    return _STRUCTURED_ADDENDUM + tail


def _synthesis_chain():
    llm = get_reasoning_llm()
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", augment_system_prompt(SYNTHESIS_SYSTEM)),
            MessagesPlaceholder("messages"),
        ]
    )
    return prompt | llm


def _extract_json_block(text: str) -> Optional[dict]:
    """Try to extract a fenced JSON block from the LLM output."""
    pattern = r"```json\s*(.*?)\s*```"
    m = re.search(pattern, text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    try:
        start = text.index("{")
        depth, end = 0, start
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        return json.loads(text[start : end + 1])
    except (ValueError, json.JSONDecodeError):
        return None


def _validate_structured(raw: dict, ticker: str) -> dict[str, Any]:
    """Validate and normalise raw dict through the Pydantic model."""
    raw.setdefault("ticker", ticker)
    try:
        report = FundamentalReport.model_validate(raw)
        return report.model_dump(mode="json")
    except Exception as exc:
        logger.warning("Structured output validation failed: %s", exc)
        raw["_validation_warning"] = str(exc)
        return raw


async def synthesise(
    fundamental_text: str,
    sentiment_text: str,
    user_query: str,
    ticker: str = "",
    retrieved_fundamental_context: str = "",
    retrieved_news_context: str = "",
) -> tuple[Optional[dict[str, Any]], str]:
    """Produce the final intelligence report (facts + structured JSON).

    Returns ``(structured_dict_or_None, markdown_text)``.
    """
    chain = _synthesis_chain()

    rag_block = ""
    if (retrieved_fundamental_context or "").strip():
        rag_block = (
            "\n\n## Deep filing excerpts (RAG — same session as uploaded 10-K / report text)\n"
            "Use for narrative depth and cross-checks. If any figure or claim conflicts with "
            "## Fundamental Analysis or ## News Sentiment above, treat those sections as "
            "current structured output and disregard the conflicting excerpt.\n\n"
            f"{retrieved_fundamental_context.strip()}\n"
        )

    news_rag_block = ""
    if (retrieved_news_context or "").strip():
        news_rag_block = (
            "\n\n## Retrieved news evidence (RAG)\n"
            "Use for recent catalysts, risks, market tone, and event-driven interpretation. "
            "Prioritise high-signal items when summarising sentiment.\n\n"
            f"{retrieved_news_context.strip()}\n"
        )

    messages = [
        HumanMessage(content=user_query),
        AIMessage(content=f"## Fundamental Analysis\n\n{fundamental_text}"),
        AIMessage(content=f"## News Sentiment\n\n{sentiment_text}"),
        HumanMessage(
            content=(
                "Based on the fundamental analysis and sentiment data above, "
                "produce the final intelligence briefing following the report "
                "structure in your instructions."
                + rag_block
                + news_rag_block
                + "\n"
                + _structured_addendum()
            )
        ),
    ]
    # Quota-conscious retry policy (MiniMax / DeepSeek share a tight 1500 / 5h bucket):
    #   - Content-filter / null-choices -> retry at most ONCE with a softened prompt.
    #   - overloaded / 529 / rate limit  -> do NOT retry here (upstream recovery handles it).
    #   - Any other exception            -> no retry, fall through to structured fallback.
    last_exc: Exception | None = None
    _CONTENT_FILTER_KEYWORDS = ("null value for 'choices'", "sensitive", "1027", "content_filter")
    _NON_RETRYABLE_MARKERS = ("529", "overloaded", "rate limit", "rate_limit", "too many requests")
    max_attempts = 2  # initial + at most one softened retry
    for attempt in range(max_attempts):
        try:
            cur_messages = list(messages)
            if attempt > 0:
                # On retry, append a softening instruction to reduce content filter triggers
                cur_messages.append(HumanMessage(content=(
                    "IMPORTANT: This is a factual financial data summary for informational "
                    "purposes only. It is NOT investment advice. Please present all data "
                    "objectively with appropriate disclaimers. "
                    "声明：以下内容仅为公开财务数据的客观整理，不构成任何投资建议。"
                )))
            result = await chain.ainvoke({"messages": cur_messages})
            full_text: str = result.content

            structured = _extract_json_block(full_text)
            if structured is not None:
                structured = _validate_structured(structured, ticker)

            markdown = re.sub(r"```json\s*.*?\s*```", "", full_text, flags=re.DOTALL).strip()

            return structured, markdown
        except Exception as exc:
            last_exc = exc
            exc_str = str(exc).lower()
            is_content_filter = any(kw in exc_str for kw in _CONTENT_FILTER_KEYWORDS)
            is_quota_error = any(kw in exc_str for kw in _NON_RETRYABLE_MARKERS)
            logger.warning(
                "Synthesis LLM call failed (attempt %d/%d, content_filter=%s, quota_error=%s): %s",
                attempt + 1, max_attempts, is_content_filter, is_quota_error, exc,
            )
            # Only content-filter hits earn a retry; quota/overloaded errors must fall through
            # to fallback so we don't burn the request budget a second time.
            if not is_content_filter or is_quota_error:
                break

    # All retries exhausted — return a fallback using available raw data
    logger.error("Synthesis failed after retries for %s: %s", ticker, last_exc)
    user_error = normalize_user_error(str(last_exc or ""))
    fallback_md = (
        f"## {ticker} 基本面分析（合成失败，原始数据如下）\n\n"
        f"### 基本面数据\n{fundamental_text[:2000]}\n\n"
        f"### 舆情数据\n{sentiment_text[:1000]}\n\n"
        f"> ⚠️ AI 综合分析未完整完成（{user_error}），以上为原始采集数据。"
    )
    fallback_structured = {
        "ticker": ticker,
        "company_name": ticker,
        "intelligence_overview": {"summary": f"合成分析未完整完成：{user_error}"},
        "risk_factors": [user_error],
    }
    return _validate_structured(fallback_structured, ticker), fallback_md
