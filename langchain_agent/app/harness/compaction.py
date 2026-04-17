"""Conversation compaction — keeps the context window lean.

When the ``TokenBudgetManager`` signals that the context window is filling up,
this module summarises older messages into a single compact digest while
preserving the most recent exchanges verbatim.

Usage::

    from app.harness.compaction import compact_conversation

    new_messages = await compact_conversation(messages, budget)
"""

from __future__ import annotations

import logging
import re
from typing import Sequence

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from app.harness.context import TokenBudgetManager, estimate_tokens

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Number of most-recent messages to keep verbatim (not compacted)
KEEP_RECENT: int = 6

# Maximum tokens for the compaction summary itself
SUMMARY_MAX_TOKENS: int = 500

# System-prompt template prepended to the compacted summary
_COMPACTION_SYSTEM = """\
You are a context compressor. Summarise the following conversation history
into a concise paragraph (max 200 words). Preserve:
- Key decisions made
- Important data points / numbers
- Analysis conclusions
- User preferences expressed
Output ONLY the summary paragraph, nothing else."""


# ---------------------------------------------------------------------------
# Summary validation
# ---------------------------------------------------------------------------

# Patterns for critical entities that MUST survive compaction
_TICKER_PAT = re.compile(
    r"(?<![A-Za-z])([A-Z]{1,5})(?![A-Za-z])"   # US ticker
    r"|(\d{4,5}\.HK)",                           # HK ticker
)
_TICKER_STOP = frozenset({
    "I", "A", "AI", "API", "CEO", "CFO", "CTO", "COO", "IPO", "ETF",
    "GDP", "PE", "PB", "ROE", "EPS", "RSI", "MACD", "SMA", "EMA",
    "OK", "THE", "FOR", "AND", "NOT", "BUT", "TOP", "VS", "OR",
    "USD", "HKD", "CNY", "EUR", "GBP", "JSON", "CSV", "SQL",
})
_NUMBER_PAT = re.compile(r"\d+\.?\d*%|\$[\d,.]+[BMT]?|\d{2,}\.?\d*")


def _validate_summary(original: str, summary: str) -> bool:
    """Check that critical tickers and significant numbers survive compaction.

    Returns True if the summary is acceptable, False if critical data was lost.
    Tolerant: requires ≥ 50% of tickers and ≥ 30% of significant numbers to
    be retained (exact match in summary text).
    """
    # Extract tickers from original
    orig_tickers: set[str] = set()
    for m in _TICKER_PAT.finditer(original):
        us, hk = m.group(1), m.group(2)
        tok = us or hk or ""
        if tok and tok not in _TICKER_STOP:
            orig_tickers.add(tok)

    # Extract significant numbers (prices, percentages, large figures)
    orig_numbers: set[str] = set(_NUMBER_PAT.findall(original))

    if not orig_tickers and not orig_numbers:
        return True  # nothing critical to validate

    # Check ticker retention
    if orig_tickers:
        retained_tickers = sum(1 for t in orig_tickers if t in summary)
        ticker_ratio = retained_tickers / len(orig_tickers)
        if ticker_ratio < 0.5:
            logger.debug(
                "_validate_summary: ticker retention %.0f%% (%d/%d) below 50%%",
                ticker_ratio * 100, retained_tickers, len(orig_tickers),
            )
            return False

    # Check number retention (more lenient — numbers may be reformatted)
    if len(orig_numbers) > 2:
        retained_nums = sum(1 for n in orig_numbers if n in summary)
        num_ratio = retained_nums / len(orig_numbers)
        if num_ratio < 0.3:
            logger.debug(
                "_validate_summary: number retention %.0f%% (%d/%d) below 30%%",
                num_ratio * 100, retained_nums, len(orig_numbers),
            )
            return False

    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def compact_conversation(
    messages: Sequence[BaseMessage],
    budget: TokenBudgetManager | None = None,
    *,
    keep_recent: int = KEEP_RECENT,
    force: bool = False,
) -> list[BaseMessage]:
    """Return a (possibly compacted) copy of *messages*.

    If the budget does not require compaction (and *force* is False), the
    original list is returned unchanged.

    Args:
        messages:    The full conversation message list.
        budget:      Optional budget manager; when provided, compaction is
                     triggered only if ``budget.should_compact()`` is True.
        keep_recent: Number of tail messages to preserve verbatim.
        force:       Bypass the budget check and always compact.

    Returns:
        A new list where older messages have been replaced by a single
        ``SystemMessage`` containing the digest.
    """
    if not messages:
        return list(messages)

    needs_compact = force or (budget is not None and budget.should_compact())
    if not needs_compact:
        return list(messages)

    if len(messages) <= keep_recent:
        logger.debug("compact_conversation: only %d messages — nothing to compact", len(messages))
        return list(messages)

    # --- Token-aware retention: keep as many recent messages as fit in
    #     the conversation budget, but at least 2 and at most keep_recent.
    if budget is not None:
        conv_limit = budget.limit_for("conversation")
        kept = 0
        kept_tokens = 0
        for m in reversed(messages):
            content = m.content if isinstance(m.content, str) else str(m.content)
            msg_tokens = estimate_tokens(content)
            if kept_tokens + msg_tokens > conv_limit and kept >= 2:
                break
            kept_tokens += msg_tokens
            kept += 1
        keep_recent = max(2, min(kept, keep_recent))

    older = messages[:-keep_recent]
    recent = messages[-keep_recent:]

    # Build a plain-text representation of the older messages
    lines: list[str] = []
    for m in older:
        role = "user" if isinstance(m, HumanMessage) else "assistant"
        content = m.content if isinstance(m.content, str) else str(m.content)
        # Truncate very long individual messages before sending to summariser
        if len(content) > 800:
            content = content[:800] + "…"
        lines.append(f"[{role}] {content}")

    older_text = "\n".join(lines)
    older_tokens = estimate_tokens(older_text)

    if older_tokens < 200:
        # Too few tokens to bother summarising
        logger.debug("compact_conversation: older section only %d tokens — skipping", older_tokens)
        return list(messages)

    logger.info(
        "compact_conversation: compacting %d older messages (%d est. tokens) → summary",
        len(older),
        older_tokens,
    )

    # --- Summarise using the same LLM factory the rest of the system uses ---
    try:
        from app.llm.factory import create_llm

        llm = create_llm(role="reasoning", temperature=0.0, max_tokens=SUMMARY_MAX_TOKENS)
        resp = await llm.ainvoke([
            {"role": "system", "content": _COMPACTION_SYSTEM},
            {"role": "user", "content": older_text},
        ])
        summary = resp.content.strip() if resp.content else ""
    except Exception as exc:
        logger.warning("compact_conversation: LLM summarisation failed (%s) — keeping originals", exc)
        return list(messages)

    if not summary:
        return list(messages)

    # --- Harness: validate summary retains critical entities ---
    if not _validate_summary(older_text, summary):
        logger.warning(
            "compact_conversation: summary failed validation "
            "(critical tickers/numbers lost) — keeping originals"
        )
        return list(messages)

    # Update budget if provided
    if budget is not None:
        new_tokens = estimate_tokens(summary)
        budget.set_usage("conversation", new_tokens + sum(
            estimate_tokens(m.content if isinstance(m.content, str) else str(m.content))
            for m in recent
        ))
        logger.info(
            "compact_conversation: reduced conversation tokens from %d to %d",
            older_tokens + sum(
                estimate_tokens(m.content if isinstance(m.content, str) else str(m.content))
                for m in recent
            ),
            budget.used("conversation"),
        )

    compacted: list[BaseMessage] = [
        SystemMessage(content=f"[对话历史摘要]\n{summary}"),
        *recent,
    ]
    return compacted
