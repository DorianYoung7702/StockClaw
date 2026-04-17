"""ReAct sub-agent for news sentiment analysis.

Exposes two factory functions:
- ``create_sentiment_agent()`` — the original ReAct agent (backward compat).
- ``create_sentiment_subgraph()`` — a compiled sub-graph suitable for
  Supervisor delegation via LangGraph ``Send()`` API.
"""

from __future__ import annotations

from typing import Any, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph import END, StateGraph, add_messages
from langgraph.prebuilt import create_react_agent
from typing_extensions import Annotated, TypedDict

from app.llm.factory import get_tool_calling_llm
from app.prompts.response_policy import augment_system_prompt
from app.prompts.sentiment import SENTIMENT_SYSTEM
from app.tools import SENTIMENT_TOOLS, SENTIMENT_TOOLS_WRAPPED

RECURSION_LIMIT = 8


# --- Sub-graph state (isolated from main AgentState) ---

class SentimentSubState(TypedDict):
    """Independent state for the sentiment sub-agent."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    tickers: list[str]
    result_text: str


def create_sentiment_agent():
    """Build a ReAct agent that fetches news and assesses sentiment.

    Uses harness-wrapped tools with automatic output truncation to keep
    the context window lean.  Falls back to raw tools if wrapping fails.
    """
    llm = get_tool_calling_llm()
    tools = SENTIMENT_TOOLS_WRAPPED or SENTIMENT_TOOLS
    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=augment_system_prompt(SENTIMENT_SYSTEM),
    )


async def _sentiment_worker(state: SentimentSubState) -> dict[str, Any]:
    """Execute the sentiment ReAct agent and extract the final text."""
    from langchain_core.messages import AIMessage, HumanMessage

    tickers = state.get("tickers", [])
    ticker_str = ", ".join(tickers)
    agent = create_sentiment_agent()
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=f"Analyse recent news sentiment for: {ticker_str}")]},
        config={"recursion_limit": RECURSION_LIMIT},
    )
    final = ""
    for m in reversed(result.get("messages", [])):
        if isinstance(m, AIMessage) and m.content:
            final = m.content
            break
    return {"result_text": final}


def create_sentiment_subgraph():
    """Build a compiled sub-graph for Supervisor delegation."""
    graph = StateGraph(SentimentSubState)
    graph.add_node("worker", _sentiment_worker)
    graph.set_entry_point("worker")
    graph.add_edge("worker", END)
    return graph.compile()
