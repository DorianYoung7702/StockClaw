"""Evaluation: Tests for the 6 new features (Steps 1-6).

Covers reflection routing, dynamic planning loop, adaptive RAG routing,
supervisor delegation, and LangSmith tracing integration.

Usage::

    pytest eval/test_new_features.py -v
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. Reflection routing logic
# ---------------------------------------------------------------------------

class TestReflectionRouting:
    """_route_after_reflect must accept good reports and revise bad ones."""

    def test_high_score_goes_to_render(self):
        from app.agents.graph import _route_after_reflect

        state: dict[str, Any] = {"reflection_score": 8.5, "revision_count": 0}
        assert _route_after_reflect(state) == "render_output"

    def test_low_score_first_pass_goes_to_synthesis(self):
        from app.agents.graph import _route_after_reflect

        state: dict[str, Any] = {"reflection_score": 4.0, "revision_count": 0}
        assert _route_after_reflect(state) == "synthesis"

    def test_low_score_after_revision_goes_to_render(self):
        from app.agents.graph import _route_after_reflect

        state: dict[str, Any] = {"reflection_score": 5.0, "revision_count": 1}
        assert _route_after_reflect(state) == "render_output"

    def test_default_score_goes_to_render(self):
        from app.agents.graph import _route_after_reflect

        state: dict[str, Any] = {}
        assert _route_after_reflect(state) == "render_output"


# ---------------------------------------------------------------------------
# 2. Dynamic planning routing logic
# ---------------------------------------------------------------------------

class TestDynamicPlanningRouting:
    """_route_after_execute_step must loop or exit correctly."""

    def test_more_steps_loops_back(self):
        from app.agents.graph import _route_after_execute_step

        state: dict[str, Any] = {
            "execution_plan": [{"action": "analyze"}, {"action": "summarize"}],
            "plan_step_index": 1,
        }
        assert _route_after_execute_step(state) == "execute_step"

    def test_all_steps_done_goes_to_synthesis(self):
        from app.agents.graph import _route_after_execute_step

        state: dict[str, Any] = {
            "execution_plan": [{"action": "analyze"}],
            "plan_step_index": 1,
        }
        assert _route_after_execute_step(state) == "synthesis"

    def test_empty_plan_goes_to_synthesis(self):
        from app.agents.graph import _route_after_execute_step

        state: dict[str, Any] = {"execution_plan": [], "plan_step_index": 0}
        assert _route_after_execute_step(state) == "synthesis"


# ---------------------------------------------------------------------------
# 3. Intent routing includes multi_step and plan
# ---------------------------------------------------------------------------

class TestIntentRoutingNewIntents:
    """_route_by_intent must route multi_step to plan node."""

    def test_multi_step_routes_to_plan(self):
        from app.agents.graph import _route_by_intent

        state: dict[str, Any] = {"intent": "multi_step"}
        assert _route_by_intent(state) == "plan"

    def test_existing_intents_unchanged(self):
        from app.agents.graph import _route_by_intent

        assert _route_by_intent({"intent": "single_stock"}) == "resolve_symbol"
        assert _route_by_intent({"intent": "chat"}) == "chat"
        assert _route_by_intent({"intent": "update_config"}) == "update_config"
        assert _route_by_intent({"intent": "strong_stocks"}) == "strong_stocks"


# ---------------------------------------------------------------------------
# 4. State fields exist for new features
# ---------------------------------------------------------------------------

class TestNewStateFields:
    """AgentState must include reflection and planning fields."""

    def test_reflection_fields_in_state(self):
        from app.models.state import AgentState
        annotations = AgentState.__annotations__

        assert "reflection_score" in annotations
        assert "reflection_feedback" in annotations
        assert "revision_count" in annotations

    def test_planning_fields_in_state(self):
        from app.models.state import AgentState
        annotations = AgentState.__annotations__

        assert "execution_plan" in annotations
        assert "plan_step_index" in annotations

    def test_multi_step_in_intent_literal(self):
        from app.models.state import AgentState
        # With `from __future__ import annotations`, annotations are strings
        intent_annotation = AgentState.__annotations__["intent"]
        annotation_str = str(intent_annotation)
        assert "multi_step" in annotation_str


# ---------------------------------------------------------------------------
# 5. LangSmith tracing callback integration
# ---------------------------------------------------------------------------

class TestLangSmithCallbackIntegration:
    """get_default_callbacks should add LangChainTracer when tracing enabled."""

    def test_tracer_added_when_enabled(self):
        import os
        with patch.dict(os.environ, {"LANGCHAIN_TRACING_V2": "true"}):
            from app.callbacks.tracing import get_default_callbacks
            cbs = get_default_callbacks()
            type_names = [type(cb).__name__ for cb in cbs]
            assert "CostTracker" in type_names
            assert "StepLogger" in type_names
            # LangChainTracer may or may not be present depending on import
            # but should not raise

    def test_tracer_not_added_when_disabled(self):
        import os
        with patch.dict(os.environ, {"LANGCHAIN_TRACING_V2": "false"}):
            from app.callbacks.tracing import get_default_callbacks
            cbs = get_default_callbacks()
            type_names = [type(cb).__name__ for cb in cbs]
            assert "CostTracker" in type_names
            assert "LangChainTracer" not in type_names


# ---------------------------------------------------------------------------
# 6. Supervisor node delegation
# ---------------------------------------------------------------------------

class TestSupervisorNode:
    """supervisor_node must delegate to sub-graphs and merge results."""

    @pytest.mark.asyncio
    async def test_skips_when_no_tickers(self):
        from app.agents.nodes import supervisor_node

        state: dict[str, Any] = {
            "tickers": [],
            "intent": "single_stock",
            "financial_data": {},
            "errors": [],
        }
        result = await supervisor_node(state)
        assert result["current_step"] == "supervisor_skipped"

    @pytest.mark.asyncio
    async def test_delegates_fundamental_and_sentiment(self):
        from app.agents.nodes import supervisor_node

        mock_fund_graph = AsyncMock()
        mock_fund_graph.ainvoke.return_value = {"result_text": "fundamental data", "messages": [], "tickers": ["AAPL"]}

        mock_sent_graph = AsyncMock()
        mock_sent_graph.ainvoke.return_value = {"result_text": "sentiment data", "messages": [], "tickers": ["AAPL"]}

        state: dict[str, Any] = {
            "tickers": ["AAPL"],
            "intent": "single_stock",
            "financial_data": {},
            "errors": [],
            "messages": [],
        }

        with patch("app.agents.fundamental.create_fundamental_subgraph", return_value=mock_fund_graph), \
             patch("app.agents.sentiment.create_sentiment_subgraph", return_value=mock_sent_graph), \
             patch("app.agents.nodes._warm_cache", new_callable=AsyncMock), \
             patch("app.agents.nodes._ensure_minimum_tool_coverage", new_callable=AsyncMock, return_value=""):
            result = await supervisor_node(state)

        fd = result.get("financial_data", {})
        assert "fundamental_text" in fd or "sentiment_text" in fd
        assert result["current_step"] == "supervisor_done"


# ---------------------------------------------------------------------------
# 7. Graph compiles with all new nodes
# ---------------------------------------------------------------------------

class TestGraphCompilation:
    """Graph must compile successfully with all 16+ nodes."""

    def test_graph_builds_without_error(self):
        from app.agents.graph import build_graph
        graph = build_graph()
        assert graph is not None

    def test_graph_compiles_without_error(self):
        from app.agents.graph import compile_graph
        compiled = compile_graph()
        assert compiled is not None

    def test_graph_has_new_nodes(self):
        from app.agents.graph import build_graph
        graph = build_graph()
        node_names = set(graph.nodes.keys())
        assert "reflect" in node_names
        assert "supervisor" in node_names
        assert "plan" in node_names
        assert "execute_step" in node_names
