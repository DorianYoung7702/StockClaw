"""ReAct sub-agent for fundamental data gathering and analysis.

Exposes two factory functions:
- ``create_fundamental_agent()`` — the original ReAct agent (backward compat).
- ``create_fundamental_subgraph()`` — a compiled sub-graph suitable for
  Supervisor delegation via LangGraph ``Send()`` API.
"""

from __future__ import annotations

from typing import Any, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph import END, StateGraph, add_messages
from langgraph.prebuilt import create_react_agent
from typing_extensions import Annotated, TypedDict

from app.llm.factory import get_tool_calling_llm
from app.prompts.fundamental import FUNDAMENTAL_SYSTEM
from app.prompts.response_policy import augment_system_prompt
from app.tools import FUNDAMENTAL_TOOLS, FUNDAMENTAL_TOOLS_WRAPPED

RECURSION_LIMIT = 40


# --- Sub-graph state (isolated from main AgentState) ---

class FundamentalSubState(TypedDict):
    """Independent state for the fundamental sub-agent."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    tickers: list[str]
    result_text: str


def create_fundamental_agent():
    """Build a ReAct agent that can autonomously call financial-data tools.

    Uses harness-wrapped tools with automatic output truncation to keep
    the context window lean.  Falls back to raw tools if wrapping fails.
    """
    llm = get_tool_calling_llm()
    tools = FUNDAMENTAL_TOOLS_WRAPPED or FUNDAMENTAL_TOOLS
    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=augment_system_prompt(FUNDAMENTAL_SYSTEM),
    )


async def _fundamental_worker(state: FundamentalSubState) -> dict[str, Any]:
    """Execute the fundamental ReAct agent and extract the final text."""
    from langchain_core.messages import AIMessage, HumanMessage

    tickers = state.get("tickers", [])
    ticker_str = ", ".join(tickers)
    query = (
        f"Please gather comprehensive fundamental data for: {ticker_str}\n"
        "Make sure to fetch: company profile, key metrics, income statement, "
        "balance sheet, peer comparison, and risk metrics."
    )
    agent = create_fundamental_agent()
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=query)]},
        config={"recursion_limit": RECURSION_LIMIT},
    )
    final = ""
    for m in reversed(result.get("messages", [])):
        if isinstance(m, AIMessage) and m.content:
            final = m.content
            break
    return {"result_text": final}


def create_fundamental_subgraph():
    """Build a compiled sub-graph for Supervisor delegation."""
    graph = StateGraph(FundamentalSubState)
    graph.add_node("worker", _fundamental_worker)
    graph.set_entry_point("worker")
    graph.add_edge("worker", END)
    return graph.compile()
