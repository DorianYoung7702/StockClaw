"""Tests for the validate_result node."""

from __future__ import annotations

import pytest


class TestValidateResultNode:
    @pytest.mark.asyncio
    async def test_passes_complete_report(self):
        from app.agents.nodes import validate_result_node

        state = {
            "errors": [],
            "structured_report": {
                "profitability": {"gross_margin": 0.45, "roe": 1.47},
                "growth": {"revenue_growth_yoy": 0.08},
                "valuation": {"pe_ratio": 32.0},
                "financial_health": {"debt_to_equity": 1.8},
                "intelligence_overview": {"summary": "Revenue grew; margins stable."},
                "risk_factors": ["High valuation"],
            },
        }
        result = await validate_result_node(state)
        assert len(result["errors"]) == 0

    @pytest.mark.asyncio
    async def test_flags_missing_dimension(self):
        from app.agents.nodes import validate_result_node

        state = {
            "errors": [],
            "structured_report": {
                "profitability": {"gross_margin": 0.45},
                "growth": {},
                "valuation": {"pe_ratio": 32.0},
                "financial_health": {"debt_to_equity": 1.8},
                "intelligence_overview": {"summary": "Mixed signals."},
                "risk_factors": ["Risk A"],
            },
        }
        result = await validate_result_node(state)
        assert any("growth" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_flags_no_report(self):
        from app.agents.nodes import validate_result_node

        state = {"errors": [], "structured_report": None}
        result = await validate_result_node(state)
        assert any("not generated" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_flags_missing_overview_and_highlights(self):
        from app.agents.nodes import validate_result_node

        state = {
            "errors": [],
            "structured_report": {
                "profitability": {"gross_margin": 0.45},
                "growth": {"revenue_growth_yoy": 0.08},
                "valuation": {"pe_ratio": 32.0},
                "financial_health": {"debt_to_equity": 1.8},
                "intelligence_overview": {"summary": ""},
                "highlights": [],
                "risk_factors": [],
            },
        }
        result = await validate_result_node(state)
        assert any("intelligence_overview" in e or "highlights" in e for e in result["errors"])
        assert any("risk" in e.lower() for e in result["errors"])
