"""LangGraph shared state definition."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, Optional, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from typing_extensions import NotRequired, TypedDict


def _last_value(a: str, b: str) -> str:
    """Reducer: last writer wins (for current_step during fan-out)."""
    return b


def _concat_errors(a: list[str], b: list[str]) -> list[str]:
    """Reducer: concatenate error lists from parallel nodes."""
    return a + b


def _merge_financial_data(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Merge reducer for financial_data — supports fan-out/fan-in parallel nodes.

    ``gather_data`` and ``sentiment`` run concurrently and each writes its own
    key (``fundamental_text`` vs ``sentiment_text``). This reducer combines both
    contributions without either node needing to read the other's output first.
    """
    return {**a, **b}


def _concat_evidence(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return a + b


class AgentState(TypedDict):
    """Shared state flowing through the LangGraph multi-agent graph.

    ``messages`` uses the built-in ``add_messages`` reducer so that every node
    can simply *append* new messages rather than manually merging lists.

    ``financial_data`` uses ``_merge_financial_data`` so that parallel nodes
    (``gather_data`` + ``sentiment``) can each write their own keys and
    LangGraph will merge the results before downstream nodes see the state.
    """

    messages: Annotated[Sequence[BaseMessage], add_messages]

    # Which analysis path the router selected
    intent: Literal["single_stock", "strong_stocks", "compare", "chat",
                    "update_config", "watchlist_add", "analyze_and_watch",
                    "multi_step"]

    # Ticker(s) extracted from user input
    tickers: list[str]

    # Validated ticker after resolve_symbol (empty string if unresolved)
    resolved_symbol: str

    # Raw data collected by gather_data + sentiment nodes (merge reducer for fan-in)
    financial_data: Annotated[dict[str, Any], _merge_financial_data]

    # Structured analysis result (serialised FundamentalReport or StrongStockList)
    analysis_result: Optional[dict[str, Any]]

    # FundamentalReport as dict — filled by synthesis, consumed by validate/render
    structured_report: Optional[dict[str, Any]]

    # Final Markdown text produced by render_output
    markdown_report: str

    # Errors / warnings collected across nodes
    errors: Annotated[list[str], _concat_errors]

    # Current processing step for observability
    current_step: Annotated[str, _last_value]

    # Session identifier for memory
    session_id: str

    # Filing / deep-document RAG (Chroma), filled before gather + synthesis
    retrieved_fundamental_context: NotRequired[str]
    retrieved_news_context: NotRequired[str]
    evidence_chain: Annotated[list[dict[str, Any]], _concat_evidence]
    retrieval_debug: Annotated[dict[str, Any], _merge_financial_data]

    # Mapping of ticker → company name (filled by resolve_symbol from yfinance)
    ticker_names: NotRequired[dict[str, str]]

    # Populated by resolve_symbol when multiple candidates found (Human-in-the-loop)
    ambiguous_tickers: NotRequired[list[str]]

    # Strong-stock screening parameters extracted from natural language
    # Keys: market_type, top_count, rsi_threshold, sort_by, min_volume_turnover
    screening_params: NotRequired[dict[str, Any]]

    # Screening config changes to apply in the frontend (from update_config intent)
    config_update: NotRequired[dict[str, Any]]

    # Tickers successfully added to watchlist (from watchlist_add intent)
    watchlist_update: NotRequired[list[str]]

    # --- Reflection / Self-Critique (Step 2) ---
    # Quality score (0-10) assigned by the reflect node
    reflection_score: NotRequired[float]
    # Improvement feedback from the critic LLM
    reflection_feedback: NotRequired[str]
    # Number of revision cycles completed (hard-capped at 1)
    revision_count: NotRequired[int]

    # --- Dynamic Planning (Step 5) ---
    # LLM-generated execution plan for multi_step intent
    execution_plan: NotRequired[list[dict[str, Any]]]
    # Current step index in the execution plan
    plan_step_index: NotRequired[int]

    # --- Harness: Context Engineering ---
    # Serialised TokenBudgetManager state (see app.harness.context)
    token_budget: NotRequired[dict[str, Any]]

    # --- Harness: Run Journal ---
    # Unique identifier for the current graph invocation (for audit trail)
    run_id: NotRequired[str]

    # --- Harness: User Persistence ---
    # User identifier for long-term memory and metrics
    user_id: NotRequired[str]

    # --- Harness: Task Lifecycle ---
    # Associated TaskSpec ID (empty = interactive mode, set = autonomous mode)
    task_id: NotRequired[str]
    # Previous cycle summary injected for continuity across autonomous cycles
    cycle_context: NotRequired[str]

    # --- Harness: Run Debrief (Feedback Loop) ---
    # Summary of the previous run (FCR, recovery events, quality score),
    # populated by parse_input to give downstream nodes prior-run awareness
    run_debrief: NotRequired[str]

    # --- Multi-Intent Queue ---
    # Ordered list of intents to execute sequentially.
    # Each item: {"intent": str, "tickers": list[str], "screening_params": dict, "simple": bool}
    # simple=True intents (watchlist, config) are sorted first (FIFO).
    intent_queue: NotRequired[list[dict[str, Any]]]
    # Current index into intent_queue (0-based)
    intent_queue_index: NotRequired[int]
    # Accumulated result summaries from each completed intent in the queue
    intent_results: NotRequired[list[str]]

    # --- Harness: Tool Rate Limiting (Architecture Constraints) ---
    # Global tool invocation counter for the current run
    tool_call_count: NotRequired[int]
