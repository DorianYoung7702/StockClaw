"""Tests for ToolRateLimiter.

Verifies:
- Calls within limits are allowed
- Per-tool limit triggers rejection
- Global limit triggers rejection
- Override per-tool limits
- Summary and rejection diagnostics
"""

from __future__ import annotations

import pytest

from app.harness.rate_limiter import ToolRateLimiter


class TestAllowWithinLimits:
    def test_single_call_allowed(self):
        lim = ToolRateLimiter(global_limit=10, per_tool_limit=5)
        assert lim.allow("get_company_profile") is True
        assert lim.total == 1

    def test_multiple_tools_allowed(self):
        lim = ToolRateLimiter(global_limit=10, per_tool_limit=5)
        for tool in ["tool_a", "tool_b", "tool_c"]:
            assert lim.allow(tool) is True
        assert lim.total == 3


class TestPerToolLimit:
    def test_rejects_after_per_tool_limit(self):
        lim = ToolRateLimiter(global_limit=100, per_tool_limit=3)
        for _ in range(3):
            assert lim.allow("get_news") is True
        # 4th call should be rejected
        assert lim.allow("get_news") is False
        assert lim.total == 3  # rejected call not counted

    def test_per_tool_limit_independent(self):
        """Different tools have separate counters."""
        lim = ToolRateLimiter(global_limit=100, per_tool_limit=2)
        assert lim.allow("tool_a") is True
        assert lim.allow("tool_a") is True
        assert lim.allow("tool_a") is False
        # tool_b should still be allowed
        assert lim.allow("tool_b") is True
        assert lim.allow("tool_b") is True
        assert lim.allow("tool_b") is False


class TestGlobalLimit:
    def test_rejects_after_global_limit(self):
        lim = ToolRateLimiter(global_limit=3, per_tool_limit=10)
        assert lim.allow("t1") is True
        assert lim.allow("t2") is True
        assert lim.allow("t3") is True
        # Global limit reached
        assert lim.allow("t4") is False

    def test_global_limit_across_tools(self):
        lim = ToolRateLimiter(global_limit=4, per_tool_limit=3)
        assert lim.allow("a") is True
        assert lim.allow("a") is True
        assert lim.allow("b") is True
        assert lim.allow("b") is True
        # 5th total call
        assert lim.allow("c") is False


class TestOverrides:
    def test_override_increases_limit(self):
        lim = ToolRateLimiter(
            global_limit=100, per_tool_limit=2,
            overrides={"special_tool": 5},
        )
        for i in range(5):
            assert lim.allow("special_tool") is True, f"call {i+1} should pass"
        assert lim.allow("special_tool") is False

    def test_override_decreases_limit(self):
        lim = ToolRateLimiter(
            global_limit=100, per_tool_limit=10,
            overrides={"restricted": 1},
        )
        assert lim.allow("restricted") is True
        assert lim.allow("restricted") is False


class TestSummaryAndRejections:
    def test_summary_structure(self):
        lim = ToolRateLimiter(global_limit=10, per_tool_limit=3)
        lim.allow("a")
        lim.allow("a")
        lim.allow("b")
        s = lim.summary()
        assert s["total_calls"] == 3
        assert s["global_limit"] == 10
        assert s["per_tool_counts"] == {"a": 2, "b": 1}
        assert s["rejections"] == 0

    def test_rejections_tracked(self):
        lim = ToolRateLimiter(global_limit=2, per_tool_limit=5)
        lim.allow("x")
        lim.allow("y")
        lim.allow("z")  # rejected
        assert len(lim.rejections) == 1
        assert lim.rejections[0]["tool"] == "z"
        assert lim.rejections[0]["reason"] == "global_limit"

    def test_per_tool_rejection_tracked(self):
        lim = ToolRateLimiter(global_limit=100, per_tool_limit=1)
        lim.allow("tool")
        lim.allow("tool")  # rejected
        assert len(lim.rejections) == 1
        assert lim.rejections[0]["reason"] == "per_tool_limit"
