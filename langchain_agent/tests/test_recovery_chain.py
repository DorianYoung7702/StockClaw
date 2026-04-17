"""Tests for the multi-level RecoveryChain and ProviderHealthTracker.

Verifies:
- L1 retry with exponential back-off succeeds on transient errors
- L1 exhaustion → L2 fallback provider ordering by health score
- L2 exhaustion → L3 graceful degradation (when degradable=True)
- L3 disabled → L4 escalation
- ProviderHealthTracker sliding window, score, and ranking
- RecoveryEvent.suggested_fix is populated at every level
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from app.harness.recovery import (
    RecoveryChain,
    RecoveryEvent,
    ProviderHealthTracker,
    get_provider_health_tracker,
    _suggest_fix_l1,
)


# ---------------------------------------------------------------------------
# ProviderHealthTracker
# ---------------------------------------------------------------------------

class TestProviderHealthTracker:
    def test_unknown_provider_returns_default(self):
        t = ProviderHealthTracker()
        assert t.score("unknown") == 0.5

    def test_score_after_successes(self):
        t = ProviderHealthTracker()
        for _ in range(4):
            t.record("yfinance", True)
        assert t.score("yfinance") == 1.0

    def test_score_after_mixed(self):
        t = ProviderHealthTracker()
        t.record("fmp", True)
        t.record("fmp", False)
        assert t.score("fmp") == 0.5

    def test_sliding_window(self):
        t = ProviderHealthTracker(window_size=3)
        t.record("api", False)
        t.record("api", False)
        t.record("api", True)
        t.record("api", True)
        t.record("api", True)
        # window=[True, True, True] (oldest 2 dropped)
        assert t.score("api") == 1.0

    def test_rank_orders_by_health(self):
        t = ProviderHealthTracker()
        for _ in range(5):
            t.record("bad", False)
        for _ in range(5):
            t.record("good", True)
        t.record("mid", True)
        t.record("mid", False)
        ranked = t.rank(["bad", "mid", "good"])
        assert ranked == ["good", "mid", "bad"]

    def test_summary_format(self):
        t = ProviderHealthTracker()
        t.record("x", True)
        t.record("x", False)
        s = t.summary()
        assert "x" in s
        assert s["x"]["total"] == 2
        assert s["x"]["successes"] == 1


# ---------------------------------------------------------------------------
# _suggest_fix_l1
# ---------------------------------------------------------------------------

class TestSuggestFix:
    def test_timeout(self):
        fix = _suggest_fix_l1(TimeoutError("timed out"), 1, 3)
        assert "timed out" in fix.lower() or "timeout" in fix.lower()

    def test_rate_limit(self):
        fix = _suggest_fix_l1(Exception("429 rate limit exceeded"), 1, 3)
        assert "rate" in fix.lower()

    def test_connection(self):
        fix = _suggest_fix_l1(ConnectionError("connection refused"), 1, 3)
        assert "connection" in fix.lower()

    def test_exhausted(self):
        fix = _suggest_fix_l1(Exception("some error"), 3, 3)
        assert "exhaust" in fix.lower()


# ---------------------------------------------------------------------------
# RecoveryChain integration (async)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_emit():
    """Disable SSE emission during tests."""
    with patch.object(RecoveryChain, "_emit", new_callable=AsyncMock):
        yield


class TestRecoveryChainL1:
    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        chain = RecoveryChain("test_node", max_retry=3, base_delay=0.01)
        func = AsyncMock(return_value={"data": "ok"})
        result = await chain.execute(func, {"errors": []})
        assert result == {"data": "ok"}
        assert len(chain.events) == 0  # no recovery needed

    @pytest.mark.asyncio
    async def test_succeeds_on_retry(self):
        call_count = 0

        async def flaky(state):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return {"data": "recovered"}

        chain = RecoveryChain("test_node", max_retry=3, base_delay=0.01)
        result = await chain.execute(flaky, {"errors": []})
        assert result["data"] == "recovered"
        # Should have 1 event for the successful retry
        assert any(e.resolution == "succeeded_on_retry" for e in chain.events)

    @pytest.mark.asyncio
    async def test_exhausts_retries_then_escalates(self):
        """No fallback, not degradable → should go L1 → L4."""
        func = AsyncMock(side_effect=RuntimeError("permanent"))
        chain = RecoveryChain(
            "test_node", max_retry=2, base_delay=0.01,
            degradable=False, fallback_providers=[],
        )
        result = await chain.execute(func, {"errors": []})
        assert "escalated" in result["current_step"]
        levels = [e.level for e in chain.events]
        assert 1 in levels and 4 in levels


class TestRecoveryChainL2:
    @pytest.mark.asyncio
    async def test_fallback_provider_succeeds(self):
        call_count = 0

        async def func_with_fallback(state):
            nonlocal call_count
            call_count += 1
            if "_fallback_provider" not in state:
                raise RuntimeError("primary failed")
            return {"data": f"from_{state['_fallback_provider']}"}

        chain = RecoveryChain(
            "test_node", max_retry=1, base_delay=0.01,
            fallback_providers=["backup_api"],
        )
        result = await chain.execute(func_with_fallback, {"errors": []})
        assert result["data"] == "from_backup_api"
        assert any(e.level == 2 and "fallback_to_" in e.resolution for e in chain.events)

    @pytest.mark.asyncio
    async def test_fallback_ordered_by_health(self):
        """Providers should be tried in health-score order."""
        tracker = get_provider_health_tracker()
        # Make 'healthy' better than 'sick'
        for _ in range(5):
            tracker.record("healthy", True)
            tracker.record("sick", False)

        tried_order = []

        async def func_that_logs(state):
            fb = state.get("_fallback_provider")
            if fb:
                tried_order.append(fb)
            raise RuntimeError("always fail")

        chain = RecoveryChain(
            "test_node", max_retry=1, base_delay=0.01,
            fallback_providers=["sick", "healthy"],
            degradable=True,
        )
        await chain.execute(func_that_logs, {"errors": []})
        # 'healthy' should be tried before 'sick'
        assert tried_order[0] == "healthy"


class TestRecoveryChainL3:
    @pytest.mark.asyncio
    async def test_degrade_when_enabled(self):
        func = AsyncMock(side_effect=RuntimeError("fail"))
        chain = RecoveryChain(
            "gather_data", max_retry=1, base_delay=0.01,
            degradable=True,
        )
        result = await chain.execute(func, {"errors": []})
        assert "degraded" in result["current_step"]
        assert any(e.level == 3 for e in chain.events)
        assert any(e.suggested_fix for e in chain.events if e.level == 3)


class TestRecoveryChainL4:
    @pytest.mark.asyncio
    async def test_escalate_has_suggested_fix(self):
        func = AsyncMock(side_effect=RuntimeError("fail"))
        chain = RecoveryChain(
            "synthesis", max_retry=1, base_delay=0.01,
            degradable=False,
        )
        result = await chain.execute(func, {"errors": []})
        assert "escalated" in result["current_step"]
        l4 = [e for e in chain.events if e.level == 4]
        assert len(l4) == 1
        assert l4[0].suggested_fix != ""


class TestRecoveryEvent:
    def test_to_dict_includes_suggested_fix(self):
        ev = RecoveryEvent(
            level=1, level_name="retry", node="test",
            suggested_fix="try again",
        )
        d = ev.to_dict()
        assert d["suggested_fix"] == "try again"

    def test_to_dict_omits_empty_fix(self):
        ev = RecoveryEvent(level=1, level_name="retry", node="test")
        d = ev.to_dict()
        assert "suggested_fix" not in d
