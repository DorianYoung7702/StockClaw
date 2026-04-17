"""Main LangGraph state-machine definition."""

from __future__ import annotations

from typing import Literal, Union

from langgraph.graph import END, StateGraph

from app.agents.nodes import (
    advance_queue_node,
    chat_node,
    execute_step_node,
    gather_data_node,
    human_confirm_node,
    parse_input_node,
    plan_node,
    reflect_node,
    render_output_node,
    resolve_symbol_node,
    retrieve_fundamental_rag_node,
    sentiment_node,
    strong_stocks_node,
    supervisor_node,
    synthesis_node,
    update_config_node,
    validate_result_node,
)
from app.models.state import AgentState


def _route_by_intent(
    state: AgentState,
) -> Literal["resolve_symbol", "strong_stocks", "chat", "update_config", "plan"]:
    """Conditional edge: route to the appropriate sub-graph based on intent.

    Handles both single-intent and multi-intent queue modes.
    watchlist_add / watchlist_remove are routed to chat (which executes
    them directly via tool call in its Phase 0).
    """
    intent = state.get("intent", "chat")
    if intent in ("single_stock", "compare"):
        return "resolve_symbol"
    elif intent == "strong_stocks":
        return "strong_stocks"
    elif intent == "update_config":
        return "update_config"
    elif intent == "multi_step":
        return "plan"
    # watchlist_add, watchlist_remove, chat → all go to chat node
    return "chat"


def _route_after_execute_step(
    state: AgentState,
) -> Literal["execute_step", "synthesis"]:
    """After executing a plan step: loop back if more steps remain, else go to synthesis."""
    plan = state.get("execution_plan", [])
    idx = state.get("plan_step_index", 0)
    if idx < len(plan):
        return "execute_step"
    return "synthesis"


def _route_after_resolve(
    state: AgentState,
) -> Literal["human_confirm", "retrieve_fundamental_rag", "__end__"]:
    """After symbol resolution: pause for human confirmation when ticker is ambiguous."""
    if not state.get("resolved_symbol"):
        return "__end__"
    if state.get("ambiguous_tickers"):
        return "human_confirm"
    return "retrieve_fundamental_rag"


def _route_after_fundamental_rag(
    state: AgentState,
) -> Union[list[str], Literal["synthesis"]]:
    """Fan-out after RAG retrieval.

    * ``strong_stocks``: straight to synthesis.
    * ``single_stock`` / ``compare``: fan-out to gather_data + sentiment.
    """
    intent = state.get("intent")
    if intent == "strong_stocks":
        return "synthesis"
    return ["gather_data", "sentiment"]


def _route_after_chat(
    state: AgentState,
) -> Literal["resolve_symbol", "strong_stocks", "update_config", "plan", "advance_queue"]:
    """After chat orchestrator: dispatch to specialised agent or advance queue.

    The chat node detects actionable intents and updates state.intent.
    If intent is still 'chat', the node already produced a response → advance_queue
    (which will either pop the next intent or finish).
    """
    intent = state.get("intent", "chat")
    step = state.get("current_step", "")
    if step == "chat_dispatched":
        if intent in ("single_stock", "compare"):
            return "resolve_symbol"
        elif intent == "strong_stocks":
            return "strong_stocks"
        elif intent == "update_config":
            return "update_config"
        elif intent == "multi_step":
            return "plan"
    return "advance_queue"


def _route_after_advance_queue(
    state: AgentState,
) -> Literal["resolve_symbol", "strong_stocks", "chat", "update_config", "plan", "__end__"]:
    """After advancing the intent queue: route to next intent or finish."""
    step = state.get("current_step", "")
    if step == "queue_next":
        return _route_by_intent(state)
    return "__end__"


def _route_after_reflect(
    state: AgentState,
) -> Literal["render_output", "synthesis"]:
    """After reflection: route back to synthesis for revision if score is low.

    Rules:
    - score >= 7  → accept, go to render
    - revision_count >= 1 → already revised once, accept as-is
    - otherwise → increment revision_count and re-run synthesis
    """
    score = state.get("reflection_score", 10.0)
    revision_count = state.get("revision_count", 0)
    if score >= 7 or revision_count >= 1:
        return "render_output"
    return "synthesis"


def build_graph() -> StateGraph:
    """Construct the multi-agent analysis graph.

    Current flow (with multi-intent queue)::

        START → parse_input → route
          ├─ single_stock/compare → resolve_symbol → … → render → advance_queue → [next or END]
          ├─ strong_stocks        → strong_stocks → … → render → advance_queue → [next or END]
          ├─ update_config        → update_config → advance_queue → [next or END]
          ├─ multi_step           → plan → execute_step loop → synthesis → … → render → advance_queue
          └─ chat/watchlist_*     → chat (orchestrator) → advance_queue → [next or END]

    Multi-intent queue:
    - ``parse_input`` builds ``intent_queue`` sorted simple-first.
    - ``advance_queue`` pops the next intent after each sub-flow completes.
    - Single-intent requests work identically (queue of length 1).

    Key design decisions:
    - ``gather_data`` and ``sentiment`` run **concurrently** (fan-out/fan-in).
    - ``financial_data`` uses a merge reducer for parallel writes.
    - ``human_confirm`` is an interrupt node for ticker disambiguation.
    - ``advance_queue`` loops back to ``_route_by_intent`` until queue is exhausted.
    """
    graph = StateGraph(AgentState)

    graph.add_node("parse_input", parse_input_node)
    graph.add_node("resolve_symbol", resolve_symbol_node)
    graph.add_node("human_confirm", human_confirm_node)
    graph.add_node("gather_data", gather_data_node)
    graph.add_node("strong_stocks", strong_stocks_node)
    graph.add_node("sentiment", sentiment_node)
    graph.add_node("retrieve_fundamental_rag", retrieve_fundamental_rag_node)
    graph.add_node("synthesis", synthesis_node)
    graph.add_node("validate_result", validate_result_node)
    graph.add_node("reflect", reflect_node)
    graph.add_node("render_output", render_output_node)
    graph.add_node("advance_queue", advance_queue_node)
    graph.add_node("chat", chat_node)
    graph.add_node("update_config", update_config_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("plan", plan_node)
    graph.add_node("execute_step", execute_step_node)

    graph.set_entry_point("parse_input")

    graph.add_conditional_edges(
        "parse_input",
        _route_by_intent,
        {
            "resolve_symbol": "resolve_symbol",
            "strong_stocks": "strong_stocks",
            "update_config": "update_config",
            "plan": "plan",
            "chat": "chat",
        },
    )

    graph.add_conditional_edges(
        "resolve_symbol",
        _route_after_resolve,
        {
            "human_confirm": "human_confirm",
            "retrieve_fundamental_rag": "retrieve_fundamental_rag",
            "__end__": END,
        },
    )

    graph.add_edge("human_confirm", "retrieve_fundamental_rag")

    graph.add_conditional_edges(
        "retrieve_fundamental_rag",
        _route_after_fundamental_rag,
    )

    graph.add_edge("gather_data", "synthesis")
    graph.add_edge("sentiment", "synthesis")
    graph.add_edge("strong_stocks", "retrieve_fundamental_rag")
    graph.add_edge("synthesis", "validate_result")
    graph.add_edge("validate_result", "reflect")
    graph.add_conditional_edges(
        "reflect",
        _route_after_reflect,
        {"render_output": "render_output", "synthesis": "synthesis"},
    )
    # render_output → advance_queue (instead of END)
    graph.add_edge("render_output", "advance_queue")

    # chat → advance_queue (or dispatch to specialised agent)
    graph.add_conditional_edges(
        "chat",
        _route_after_chat,
        {
            "resolve_symbol": "resolve_symbol",
            "strong_stocks": "strong_stocks",
            "update_config": "update_config",
            "plan": "plan",
            "advance_queue": "advance_queue",
        },
    )
    # update_config → advance_queue (instead of END)
    graph.add_edge("update_config", "advance_queue")

    # advance_queue → route to next intent or END
    graph.add_conditional_edges(
        "advance_queue",
        _route_after_advance_queue,
        {
            "resolve_symbol": "resolve_symbol",
            "strong_stocks": "strong_stocks",
            "chat": "chat",
            "update_config": "update_config",
            "plan": "plan",
            "__end__": END,
        },
    )

    # --- Dynamic Planning loop ---
    graph.add_edge("plan", "execute_step")
    graph.add_conditional_edges(
        "execute_step",
        _route_after_execute_step,
        {"execute_step": "execute_step", "synthesis": "synthesis"},
    )

    return graph


def compile_graph(checkpointer=None):
    """Compile the graph with an optional checkpointer for session memory.

    ``interrupt_before=["human_confirm"]`` tells LangGraph to pause execution
    at the disambiguation node and wait for ``graph.update_state()`` to provide
    the user's ticker selection before resuming.
    """
    graph = build_graph()
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_confirm"],
    )
