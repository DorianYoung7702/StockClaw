"""Tests for the Agent Harness infrastructure (Phases 1-7).

Validates that all harness modules work correctly without breaking
existing agent logic.
"""

import json
import time

import pytest


# ===========================================================================
# Phase 1 — Context Engineering
# ===========================================================================


class TestTokenBudgetManager:
    def test_estimate_tokens_empty(self):
        from app.harness.context import estimate_tokens
        assert estimate_tokens("") == 0

    def test_estimate_tokens_ascii(self):
        from app.harness.context import estimate_tokens
        # "Hello World" = 11 chars → ~2-3 tokens
        result = estimate_tokens("Hello World")
        assert 1 <= result <= 5

    def test_estimate_tokens_cjk(self):
        from app.harness.context import estimate_tokens
        # 4 CJK chars → ~6 tokens (1.5 each)
        result = estimate_tokens("你好世界")
        assert 4 <= result <= 8

    def test_budget_record_and_query(self):
        from app.harness.context import TokenBudgetManager
        budget = TokenBudgetManager(model_limit=10_000)
        result = budget.record("system_prompt", "Hello " * 50)
        assert result.tokens > 0
        assert budget.used("system_prompt") == result.tokens
        assert budget.used() == result.tokens
        assert budget.remaining("system_prompt") > 0

    def test_record_returns_over_budget(self):
        from app.harness.context import TokenBudgetManager
        budget = TokenBudgetManager(model_limit=100)
        # system_prompt gets 5% = 5 tokens; fill way beyond that
        result = budget.record("system_prompt", "Hello World " * 100)
        assert result.over_budget is True

    def test_trim_to_budget(self):
        from app.harness.context import TokenBudgetManager
        budget = TokenBudgetManager(model_limit=1000)
        # rag_context gets 15% = 150 tokens
        big_text = "x" * 5000  # ~1250 tokens
        trimmed = budget.trim_to_budget("rag_context", big_text)
        assert len(trimmed) < len(big_text)
        assert len(trimmed) > 0

    def test_rebalance_redistributes(self):
        from app.harness.context import TokenBudgetManager
        budget = TokenBudgetManager(model_limit=10000)
        # Record only system_prompt and tool_results; leave rag_context,
        # long_term_memory, and conversation at zero usage.
        budget.record("system_prompt", "test" * 10)
        # tool_results budget = 30% of 10000 = 3000 tokens
        # "data" * 5000 = 20000 chars ≈ 5000 tokens → overflows
        budget.record("tool_results", "data" * 5000)
        old_tool_limit = budget.limit_for("tool_results")
        budget.rebalance()
        new_tool_limit = budget.limit_for("tool_results")
        # rag_context (15%) + long_term_memory (8%) + conversation (32%) = 55%
        # should be redistributed to tool_results
        assert new_tool_limit > old_tool_limit

    def test_should_compact(self):
        from app.harness.context import TokenBudgetManager
        budget = TokenBudgetManager(model_limit=100)
        # Fill to over 80%
        budget.set_usage("conversation", 85)
        assert budget.should_compact() is True

    def test_serialization(self):
        from app.harness.context import TokenBudgetManager
        budget = TokenBudgetManager(model_limit=50_000)
        budget.record("system_prompt", "test" * 100)
        d = budget.to_dict()
        assert "model_limit" in d
        assert "usage" in d
        assert "usage_ratio" in d
        restored = TokenBudgetManager.from_dict(d)
        assert restored.model_limit == 50_000
        assert restored.used("system_prompt") == budget.used("system_prompt")


class TestRateLimiterPerRun:
    def test_rate_limiter_is_per_instance(self):
        from app.harness.rate_limiter import ToolRateLimiter
        a = ToolRateLimiter(global_limit=2)
        b = ToolRateLimiter(global_limit=2)
        a.allow("tool_a")
        a.allow("tool_a")
        assert a.allow("tool_a") is False  # a is exhausted
        assert b.allow("tool_a") is True   # b is independent


class TestToolOutputTruncation:
    def test_short_output_unchanged(self):
        from app.harness.tool_output import truncate_tool_output
        short = "Hello World"
        assert truncate_tool_output(short) == short

    def test_json_array_truncation(self):
        from app.harness.tool_output import truncate_tool_output
        # Make items large enough so total exceeds max_chars
        big_list = json.dumps([{"title": f"Item {i}", "body": "x" * 200} for i in range(50)])
        result = truncate_tool_output(big_list, max_array_items=3)
        assert "共 50 条" in result
        parsed = json.loads(result.split("\n[")[0])
        assert len(parsed) == 3

    def test_hard_truncation(self):
        from app.harness.tool_output import truncate_tool_output
        big_text = "x" * 10000
        result = truncate_tool_output(big_text, max_chars=500)
        assert len(result) < 600
        assert "已截断" in result

    def test_validate_tool_output(self):
        from app.harness.tool_output import validate_tool_output
        result = validate_tool_output('{"key": "value"}')
        assert result["status"] == "ok"
        assert result["truncated"] is False

    def test_validate_oversized(self):
        from app.harness.tool_output import validate_tool_output
        big = json.dumps([{"x": "y" * 100} for _ in range(100)])
        result = validate_tool_output(big)
        assert result["status"] == "ok"
        assert result["truncated"] is True


# ===========================================================================
# Phase 2 — Error Recovery
# ===========================================================================


class TestCircuitBreaker:
    def test_starts_closed(self):
        from app.harness.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker("test_api", failure_threshold=3, cooldown_seconds=1)
        assert cb.state.value == "closed"
        assert cb.allow_request() is True

    def test_trips_after_threshold(self):
        from app.harness.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker("test_api2", failure_threshold=2, cooldown_seconds=60)
        cb.record_failure()
        assert cb.state.value == "closed"
        cb.record_failure()
        assert cb.state.value == "open"
        assert cb.allow_request() is False

    def test_recovers_on_success(self):
        from app.harness.circuit_breaker import CircuitBreaker
        # Use a tiny but non-zero cooldown so OPEN state is observable
        cb = CircuitBreaker("test_api3_v2", failure_threshold=1, cooldown_seconds=0.05)
        cb.record_failure()
        # Immediately after failure, should be OPEN (cooldown hasn't elapsed)
        assert cb.allow_request() is False
        # Wait past cooldown → transitions to HALF_OPEN on next check
        time.sleep(0.06)
        allowed = cb.allow_request()
        assert allowed is True  # half_open → allows probe
        cb.record_success()
        assert cb.state.value == "closed"

    def test_to_dict(self):
        from app.harness.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker("test_api4", failure_threshold=3)
        d = cb.to_dict()
        assert d["name"] == "test_api4"
        assert d["state"] == "closed"
        assert d["total_trips"] == 0

    def test_global_registry(self):
        from app.harness.circuit_breaker import get_breaker, all_breakers
        b1 = get_breaker("test_reg_1", failure_threshold=5, cooldown_seconds=30)
        b2 = get_breaker("test_reg_1")  # same name → same instance
        assert b1 is b2
        status = all_breakers()
        assert "test_reg_1" in status


class TestRecoveryChain:
    def test_recovery_event_serialization(self):
        from app.harness.recovery import RecoveryEvent
        event = RecoveryEvent(level=2, level_name="fallback", node="gather_data")
        d = event.to_dict()
        assert d["level"] == 2
        assert d["node"] == "gather_data"


# ===========================================================================
# Phase 3 — Tool Guardrails
# ===========================================================================


class TestToolPermissions:
    def test_read_tier(self):
        from app.harness.permissions import ToolPermissionGuard, ToolTier
        guard = ToolPermissionGuard()
        assert guard.get_tier("get_company_profile") == ToolTier.READ
        assert guard.check_allowed("get_company_profile") is True

    def test_compute_tier(self):
        from app.harness.permissions import ToolPermissionGuard, ToolTier
        guard = ToolPermissionGuard()
        assert guard.get_tier("get_peer_comparison") == ToolTier.COMPUTE
        assert guard.check_allowed("get_peer_comparison") is True

    def test_unknown_defaults_to_read(self):
        from app.harness.permissions import ToolPermissionGuard, ToolTier
        guard = ToolPermissionGuard()
        assert guard.get_tier("nonexistent_tool") == ToolTier.READ

    def test_write_tier_blocked(self):
        from app.harness.permissions import ToolPermissionGuard, ToolTier
        guard = ToolPermissionGuard()
        guard.register_tier("trade_execute", ToolTier.WRITE)
        assert guard.check_allowed("trade_execute") is False

    def test_write_tier_auto_approve(self):
        from app.harness.permissions import ToolPermissionGuard, ToolTier
        guard = ToolPermissionGuard(auto_approve_writes=True)
        guard.register_tier("trade_execute", ToolTier.WRITE)
        assert guard.check_allowed("trade_execute") is True

    def test_check_and_log(self):
        from app.harness.permissions import ToolPermissionGuard
        guard = ToolPermissionGuard()
        entry = guard.check_and_log("get_risk_metrics")
        assert entry["tier"] == "compute"
        assert entry["allowed"] is True
        assert entry["needs_approval"] is False


# ===========================================================================
# Phase 5 — Run Journal
# ===========================================================================


class TestRunJournal:
    def test_basic_logging(self):
        from app.harness.run_journal import RunJournal
        j = RunJournal(run_id="test_001", session_id="s1", user_id="u1")
        j.node_start("gather_data")
        j.tool_call("gather_data", "get_key_metrics")
        j.tool_result("gather_data", "get_key_metrics", chars=2000)
        j.node_end("gather_data")
        assert len(j.entries) == 4
        summary = j.summary()
        assert summary["tool_calls"] == 1
        assert summary["errors"] == 0
        assert summary["run_id"] == "test_001"

    def test_error_and_recovery_logging(self):
        from app.harness.run_journal import RunJournal
        j = RunJournal(run_id="test_002")
        j.error("sentiment", "API timeout", level=1)
        j.recovery("sentiment", level=1, resolution="retry_succeeded")
        summary = j.summary()
        assert summary["errors"] == 1
        assert summary["recoveries"] == 1
        assert summary["recovery_levels"] == [1]

    def test_compaction_logging(self):
        from app.harness.run_journal import RunJournal
        j = RunJournal(run_id="test_003")
        j.compaction(before_tokens=10000, after_tokens=3000)
        summary = j.summary()
        assert summary["compactions"] == 1

    def test_entry_serialization(self):
        from app.harness.run_journal import JournalEntry
        entry = JournalEntry(
            event_type="tool_call",
            node="gather_data",
            payload={"tool": "get_key_metrics"},
            latency_ms=150.3,
        )
        d = entry.to_dict()
        assert d["event_type"] == "tool_call"
        assert d["payload"]["tool"] == "get_key_metrics"
        assert d["latency_ms"] == 150.3


# ===========================================================================
# Phase 6 — Approval Gate
# ===========================================================================


class TestApprovalGateInGraph:
    def test_approval_gate_node_exists_in_graph(self):
        """Verify approval_gate is registered in the compiled graph."""
        from app.agents.graph import compile_graph
        graph = compile_graph()
        node_names = list(graph.get_graph().nodes.keys())
        assert "approval_gate" in node_names

    def test_graph_routing_watchlist_add_goes_through_approval(self):
        """Verify that watchlist_add intent routes through approval_gate."""
        from app.agents.graph import _route_after_resolve
        state = {"intent": "watchlist_add", "ambiguous_tickers": []}
        result = _route_after_resolve(state)
        assert result == "approval_gate"

    def test_graph_routing_single_stock_bypasses_approval(self):
        """Verify that single_stock intent goes directly to RAG."""
        from app.agents.graph import _route_after_resolve
        state = {"intent": "single_stock", "ambiguous_tickers": []}
        result = _route_after_resolve(state)
        assert result == "retrieve_fundamental_rag"


# ===========================================================================
# Phase 7 — Metrics
# ===========================================================================


class TestMetrics:
    def test_metrics_import(self):
        from app.harness.metrics import MetricsAggregator
        assert MetricsAggregator is not None

    def test_resume_bullets_format(self):
        from app.harness.metrics import MetricsAggregator
        bullets = MetricsAggregator._format_resume_bullets(
            p50=500, p95=1200,
            fcr={"total_runs": 100, "clean_runs": 85, "fcr": 0.85},
            compaction={"compaction_events": 50, "total_tokens_saved": 150000},
            recovery={"total_errors": 30, "auto_recovered": 27, "auto_recovery_rate": 0.9, "escalated": 3},
            tokens={"total_tokens": 500000, "efficiency": 0.35},
            quality={"count": 80, "mean": 8.2},
            users={"total_users": 10, "total_sessions": 200, "total_analyses": 500},
        )
        assert len(bullets) == 7
        assert any("P95" in b for b in bullets)
        assert any("First Completion Rate" in b for b in bullets)
        assert any("compaction" in b.lower() for b in bullets)
        assert any("recovery" in b.lower() for b in bullets)


# ===========================================================================
# Integration — Wrapped tools
# ===========================================================================


class TestWrappedTools:
    def test_wrapped_tool_lists_have_correct_count(self):
        from app.tools import FUNDAMENTAL_TOOLS, FUNDAMENTAL_TOOLS_WRAPPED
        from app.tools import SENTIMENT_TOOLS, SENTIMENT_TOOLS_WRAPPED
        assert len(FUNDAMENTAL_TOOLS_WRAPPED) == len(FUNDAMENTAL_TOOLS)
        assert len(SENTIMENT_TOOLS_WRAPPED) == len(SENTIMENT_TOOLS)

    def test_wrapped_tools_preserve_name(self):
        from app.tools import FUNDAMENTAL_TOOLS, FUNDAMENTAL_TOOLS_WRAPPED
        for orig, wrapped in zip(FUNDAMENTAL_TOOLS, FUNDAMENTAL_TOOLS_WRAPPED):
            assert wrapped.name == orig.name


# ===========================================================================
# Integration — AgentState new fields
# ===========================================================================


class TestAgentStateHarnessFields:
    def test_harness_fields_in_state(self):
        from app.models.state import AgentState
        annotations = AgentState.__annotations__
        assert "token_budget" in annotations
        assert "run_id" in annotations
        assert "user_id" in annotations

    def test_harness_config_fields(self):
        from app.config import get_settings
        s = get_settings()
        assert hasattr(s, "harness_model_context_limit")
        assert hasattr(s, "harness_compaction_threshold")
        assert hasattr(s, "harness_tool_output_max_chars")
        assert hasattr(s, "harness_circuit_breaker_threshold")
        assert hasattr(s, "harness_circuit_breaker_cooldown")
        assert hasattr(s, "harness_recovery_max_retry")
        assert hasattr(s, "harness_journal_db_path")
        assert s.harness_model_context_limit == 128_000
        assert s.harness_compaction_threshold == 0.8
