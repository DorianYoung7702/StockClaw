"""Integration tests for the LangGraph agent graph."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage


class TestGraphStructure:
    """Verify the graph compiles and has expected nodes/edges."""

    def test_graph_compiles(self):
        from app.agents.graph import build_graph

        graph = build_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_graph_has_expected_nodes(self):
        from app.agents.graph import build_graph

        graph = build_graph()
        node_names = set(graph.nodes.keys())
        expected = {
            "parse_input", "resolve_symbol", "gather_data",
            "strong_stocks", "sentiment", "retrieve_fundamental_rag", "synthesis",
            "validate_result", "render_output", "chat",
        }
        assert expected.issubset(node_names)


class TestParseInputNode:
    """Test the intent-parsing node in isolation."""

    @pytest.mark.asyncio
    @patch("app.agents.nodes.get_tool_calling_llm")
    async def test_parses_single_stock_intent(self, mock_llm_factory):
        from app.agents.nodes import parse_input_node

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='{"intent": "single_stock", "tickers": ["AAPL"]}'
        )
        mock_llm_factory.return_value = mock_llm

        state = {
            "messages": [HumanMessage(content="Analyse AAPL fundamentals")],
            "intent": "chat",
            "tickers": [],
            "resolved_symbol": "",
            "financial_data": {},
            "analysis_result": None,
            "structured_report": None,
            "markdown_report": "",
            "errors": [],
            "current_step": "",
            "session_id": "test",
        }
        result = await parse_input_node(state)
        assert result["intent"] == "single_stock"
        assert "AAPL" in result["tickers"]

    @pytest.mark.asyncio
    @patch("app.agents.nodes.get_tool_calling_llm")
    async def test_parses_strong_stocks_intent(self, mock_llm_factory):
        from app.agents.nodes import parse_input_node

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='{"intent": "strong_stocks", "tickers": []}'
        )
        mock_llm_factory.return_value = mock_llm

        state = {
            "messages": [HumanMessage(content="Show me strong stocks")],
            "intent": "chat",
            "tickers": [],
            "resolved_symbol": "",
            "financial_data": {},
            "analysis_result": None,
            "structured_report": None,
            "markdown_report": "",
            "errors": [],
            "current_step": "",
            "session_id": "test",
        }
        result = await parse_input_node(state)
        assert result["intent"] == "strong_stocks"

    @pytest.mark.asyncio
    @patch("app.agents.nodes.get_tool_calling_llm")
    async def test_handles_malformed_llm_output(self, mock_llm_factory):
        from app.agents.nodes import parse_input_node

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="not valid json")
        mock_llm_factory.return_value = mock_llm

        state = {
            "messages": [HumanMessage(content="hello")],
            "intent": "chat",
            "tickers": [],
            "resolved_symbol": "",
            "financial_data": {},
            "analysis_result": None,
            "structured_report": None,
            "markdown_report": "",
            "errors": [],
            "current_step": "",
            "session_id": "test",
        }
        result = await parse_input_node(state)
        assert result["intent"] == "chat"
        assert result["tickers"] == []


class TestRouting:
    """Test the conditional routing logic."""

    def test_route_single_stock(self):
        from app.agents.graph import _route_by_intent

        state = {"intent": "single_stock"}
        assert _route_by_intent(state) == "resolve_symbol"

    def test_route_compare(self):
        from app.agents.graph import _route_by_intent

        state = {"intent": "compare"}
        assert _route_by_intent(state) == "resolve_symbol"

    def test_route_strong_stocks(self):
        from app.agents.graph import _route_by_intent

        state = {"intent": "strong_stocks"}
        assert _route_by_intent(state) == "strong_stocks"

    def test_route_chat(self):
        from app.agents.graph import _route_by_intent

        state = {"intent": "chat"}
        assert _route_by_intent(state) == "chat"

    def test_route_unknown_falls_to_chat(self):
        from app.agents.graph import _route_by_intent

        state = {"intent": "unknown"}
        assert _route_by_intent(state) == "chat"


class TestRenderOutputNode:
    """Test the render_output_node in isolation."""

    @pytest.mark.asyncio
    async def test_renders_structured_report(self):
        from app.agents.nodes import render_output_node

        state = {
            "structured_report": {
                "ticker": "AAPL",
                "company_name": "Apple Inc.",
                "industry": "Consumer Electronics",
                "current_price": 195.0,
                "profitability": {"gross_margin": 0.45, "roe": 1.47, "summary": "Good."},
                "growth": {"revenue_growth_yoy": 0.08, "summary": "Moderate."},
                "valuation": {"pe_ratio": 32.0, "summary": "Fair."},
                "financial_health": {"debt_to_equity": 1.8, "summary": "Okay."},
                "news_sentiment": {"overall": "positive", "summary": "Bullish."},
                "intelligence_overview": {"summary": "Solid fundamentals; elevated multiples."},
                "risk_factors": ["High valuation"],
                "highlights": ["Strong brand"],
            },
            "errors": [],
            "analysis_result": {},
        }
        result = await render_output_node(state)
        md = result["markdown_report"]
        assert "Apple Inc." in md
        assert "AAPL" in md
        assert "P/E" in md
        assert "High valuation" in md
        assert "Factual summary" in md
        assert "not investment advice" in md.lower()

    @pytest.mark.asyncio
    async def test_fallback_when_no_structured(self):
        from app.agents.nodes import render_output_node

        state = {
            "structured_report": None,
            "errors": ["Structured report was not generated."],
            "analysis_result": {"report": "Fallback text analysis."},
        }
        result = await render_output_node(state)
        assert "Fallback text analysis" in result["markdown_report"]
        assert "Data Limitations" in result["markdown_report"]
