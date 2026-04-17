"""Evaluation: Structured report schema validation.

Validates that ``FundamentalReport`` produced by the synthesis node conforms
to the expected Pydantic schema and covers all required analysis dimensions.

Usage::

    pytest eval/test_report_structure.py -v
"""

from __future__ import annotations

from typing import Any, Optional

import pytest
from pydantic import BaseModel, ValidationError


# ---------------------------------------------------------------------------
# Expected schema (mirrors app/models/report.py)
# ---------------------------------------------------------------------------

class _IntelligenceOverview(BaseModel):
    summary: Optional[str] = None
    recommendation: Optional[str] = None


class _Profitability(BaseModel):
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    roe: Optional[float] = None


class _Growth(BaseModel):
    revenue_growth_yoy: Optional[float] = None
    earnings_growth_yoy: Optional[float] = None


class _Valuation(BaseModel):
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    ev_to_ebitda: Optional[float] = None


class _FinancialHealth(BaseModel):
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None


class FundamentalReportSchema(BaseModel):
    """Loose validation schema — all fields optional for graceful degradation."""
    intelligence_overview: Optional[_IntelligenceOverview] = None
    profitability: Optional[_Profitability] = None
    growth: Optional[_Growth] = None
    valuation: Optional[_Valuation] = None
    financial_health: Optional[_FinancialHealth] = None
    highlights: Optional[list[str]] = None
    risk_factors: Optional[list[str]] = None
    catalysts: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Sample reports for testing (without requiring LLM)
# ---------------------------------------------------------------------------

_COMPLETE_REPORT: dict[str, Any] = {
    "intelligence_overview": {"summary": "Apple is strong.", "recommendation": "Hold"},
    "profitability": {"gross_margin": 0.45, "operating_margin": 0.30, "net_margin": 0.25, "roe": 1.5},
    "growth": {"revenue_growth_yoy": 0.08, "earnings_growth_yoy": 0.12},
    "valuation": {"pe_ratio": 28.5, "pb_ratio": 45.0, "ev_to_ebitda": 22.0},
    "financial_health": {"debt_to_equity": 1.8, "current_ratio": 1.0},
    "highlights": ["Strong services revenue", "Record iPhone sales"],
    "risk_factors": ["China exposure", "Regulatory risk"],
    "catalysts": ["Apple Intelligence rollout", "Vision Pro adoption"],
}

_PARTIAL_REPORT: dict[str, Any] = {
    "intelligence_overview": {"summary": "Limited data."},
    "profitability": {"gross_margin": 0.45},
    "growth": None,
    "valuation": {"pe_ratio": 28.5},
    "financial_health": None,
    "highlights": [],
    "risk_factors": [],
}

_EMPTY_REPORT: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReportSchemaValidation:
    """Validate that reports conform to FundamentalReportSchema."""

    def test_complete_report_passes(self):
        report = FundamentalReportSchema(**_COMPLETE_REPORT)
        assert report.profitability is not None
        assert report.profitability.gross_margin == 0.45
        assert len(report.highlights) == 2
        assert len(report.risk_factors) == 2

    def test_partial_report_passes_gracefully(self):
        report = FundamentalReportSchema(**_PARTIAL_REPORT)
        assert report.profitability is not None
        assert report.growth is None
        assert report.financial_health is None

    def test_empty_report_passes_with_all_none(self):
        report = FundamentalReportSchema(**_EMPTY_REPORT)
        assert report.profitability is None
        assert report.intelligence_overview is None

    def test_invalid_type_raises_validation_error(self):
        with pytest.raises(ValidationError):
            FundamentalReportSchema(profitability="not a dict")


class TestDimensionCompleteness:
    """Check that reports cover all 4 required analysis dimensions."""

    _REQUIRED_DIMENSIONS = ["profitability", "growth", "valuation", "financial_health"]

    def _dimension_score(self, report_dict: dict[str, Any]) -> float:
        """Return fraction of dimensions that are non-null and non-empty."""
        present = 0
        for dim in self._REQUIRED_DIMENSIONS:
            section = report_dict.get(dim)
            if section and isinstance(section, dict) and any(v is not None for v in section.values()):
                present += 1
        return present / len(self._REQUIRED_DIMENSIONS)

    def test_complete_report_has_full_coverage(self):
        score = self._dimension_score(_COMPLETE_REPORT)
        assert score == 1.0

    def test_partial_report_coverage(self):
        score = self._dimension_score(_PARTIAL_REPORT)
        assert 0.0 < score < 1.0

    def test_empty_report_zero_coverage(self):
        score = self._dimension_score(_EMPTY_REPORT)
        assert score == 0.0


class TestValidateResultNodeLogic:
    """Test the validate_result_node error detection logic."""

    @pytest.mark.asyncio
    async def test_missing_dimensions_flagged(self):
        from app.agents.nodes import validate_result_node

        state: dict[str, Any] = {
            "structured_report": _PARTIAL_REPORT,
            "errors": [],
        }
        result = await validate_result_node(state)
        errors = result.get("errors", [])
        # growth and financial_health are missing → should have error messages
        assert any("增长" in e for e in errors), f"Expected growth error, got: {errors}"

    @pytest.mark.asyncio
    async def test_complete_report_minimal_errors(self):
        from app.agents.nodes import validate_result_node

        state: dict[str, Any] = {
            "structured_report": _COMPLETE_REPORT,
            "errors": [],
        }
        result = await validate_result_node(state)
        errors = result.get("errors", [])
        assert len(errors) == 0, f"Complete report should have no errors: {errors}"

    @pytest.mark.asyncio
    async def test_none_report_handled(self):
        from app.agents.nodes import validate_result_node

        state: dict[str, Any] = {
            "structured_report": None,
            "intent": "single_stock",
            "errors": [],
        }
        result = await validate_result_node(state)
        errors = result.get("errors", [])
        assert len(errors) >= 1
