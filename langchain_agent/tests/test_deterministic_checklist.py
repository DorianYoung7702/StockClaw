"""Tests for the deterministic checklist in reflect_node.

Verifies:
- User mentions debt but report lacks it → missing + penalty
- User mentions valuation AND growth → both checked independently
- No user keywords → no penalty
- Report has structured data for the dimension → passes
- Report has keyword in narrative only → passes
- Penalty capped at 4.0
"""

from __future__ import annotations

import pytest

from app.agents.nodes import _deterministic_checklist


# ---------------------------------------------------------------------------
# Helper: build a minimal structured report
# ---------------------------------------------------------------------------

def _report(**sections) -> dict:
    """Build a dict mimicking structured_report with specific sections."""
    base = {
        "valuation": {},
        "profitability": {},
        "growth": {},
        "financial_health": {},
        "risk_factors": {},
        "sentiment": {},
        "technical": {},
    }
    base.update(sections)
    return base


class TestNoKeywords:
    def test_generic_query_no_penalty(self):
        missing, penalty = _deterministic_checklist(
            "帮我分析一下AAPL", _report(), "",
        )
        assert missing == []
        assert penalty == 0.0

    def test_empty_query_no_penalty(self):
        missing, penalty = _deterministic_checklist("", _report(), "")
        assert missing == []
        assert penalty == 0.0


class TestDebtDimension:
    def test_user_asks_debt_but_missing(self):
        """User asks about debt, report has no financial_health data."""
        missing, penalty = _deterministic_checklist(
            "分析AAPL的债务情况",
            _report(financial_health={}),
            "",
        )
        assert "financial_health" in missing
        assert penalty > 0

    def test_user_asks_debt_and_present(self):
        """User asks about debt, report has debt_to_equity data."""
        missing, penalty = _deterministic_checklist(
            "AAPL 的负债率怎么样",
            _report(financial_health={"debt_to_equity": 1.5, "current_ratio": 1.1}),
            "",
        )
        assert missing == []
        assert penalty == 0.0

    def test_leverage_keyword(self):
        missing, _ = _deterministic_checklist(
            "NVDA leverage analysis",
            _report(financial_health={}),
            "",
        )
        assert "financial_health" in missing


class TestValuationDimension:
    def test_pe_keyword_triggers_check(self):
        missing, _ = _deterministic_checklist(
            "AAPL 的 PE 是多少",
            _report(valuation={}),
            "",
        )
        assert "valuation" in missing

    def test_valuation_present_with_pe(self):
        missing, _ = _deterministic_checklist(
            "估值分析",
            _report(valuation={"pe_ratio": 28.5}),
            "",
        )
        assert "valuation" not in missing


class TestGrowthDimension:
    def test_growth_missing(self):
        missing, _ = _deterministic_checklist(
            "分析AAPL的增长趋势",
            _report(growth={}),
            "",
        )
        assert "growth" in missing

    def test_growth_present(self):
        missing, _ = _deterministic_checklist(
            "revenue growth",
            _report(growth={"revenue_growth_yoy": 0.15}),
            "",
        )
        assert "growth" not in missing


class TestNarrativeFallback:
    def test_dimension_in_narrative_only(self):
        """No structured data, but narrative mentions the dimension → passes."""
        missing, _ = _deterministic_checklist(
            "分析风险因素",
            None,
            "该公司面临的 risk_factors 包括供应链中断和汇率波动。",
        )
        assert "risk_factors" not in missing

    def test_dimension_not_in_narrative(self):
        missing, _ = _deterministic_checklist(
            "分析情绪面",
            None,
            "该公司基本面良好，估值合理。",
        )
        assert "sentiment" in missing


class TestMultipleDimensions:
    def test_two_dimensions_both_missing(self):
        missing, penalty = _deterministic_checklist(
            "分析AAPL的估值和债务",
            _report(valuation={}, financial_health={}),
            "",
        )
        assert "valuation" in missing
        assert "financial_health" in missing
        assert penalty == 3.0  # 2 * 1.5

    def test_one_present_one_missing(self):
        missing, penalty = _deterministic_checklist(
            "分析AAPL的估值和债务",
            _report(
                valuation={"pe_ratio": 25},
                financial_health={},
            ),
            "",
        )
        assert "valuation" not in missing
        assert "financial_health" in missing
        assert penalty == 1.5


class TestPenaltyCap:
    def test_penalty_capped_at_4(self):
        """Even with many missing dimensions, penalty maxes at 4.0."""
        missing, penalty = _deterministic_checklist(
            "分析估值 债务 盈利 增长 风险",
            _report(),  # all sections empty
            "",
        )
        assert len(missing) >= 3  # at least 3 dimensions triggered
        assert penalty <= 4.0
