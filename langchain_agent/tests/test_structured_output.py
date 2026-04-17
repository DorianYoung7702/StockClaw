"""Tests for structured output parsing and validation."""

from __future__ import annotations

import json

import pytest

from app.models.analysis import FundamentalReport


class TestFundamentalReportModel:
    def test_minimal_valid_report(self):
        data = {
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "industry": "Consumer Electronics",
        }
        report = FundamentalReport.model_validate(data)
        assert report.ticker == "AAPL"
        assert report.profitability.gross_margin is None
        assert report.intelligence_overview.summary == ""

    def test_full_report_roundtrip(self):
        data = {
            "ticker": "NVDA",
            "company_name": "NVIDIA",
            "industry": "Semiconductors",
            "current_price": 135.0,
            "profitability": {
                "gross_margin": 0.73,
                "operating_margin": 0.54,
                "net_margin": 0.49,
                "roe": 1.15,
                "roa": 0.55,
                "summary": "Excellent margins driven by data center demand.",
            },
            "growth": {
                "revenue_growth_yoy": 1.22,
                "earnings_growth_yoy": 5.81,
                "summary": "Hyper-growth phase.",
            },
            "valuation": {
                "pe_ratio": 65.0,
                "pb_ratio": 55.0,
                "ev_to_ebitda": 50.0,
                "summary": "Premium valuation.",
            },
            "financial_health": {
                "debt_to_equity": 0.41,
                "current_ratio": 4.17,
                "summary": "Very healthy balance sheet.",
            },
            "news_sentiment": {
                "overall": "positive",
                "positive_count": 7,
                "negative_count": 1,
                "summary": "Overwhelmingly positive sentiment.",
            },
            "intelligence_overview": {
                "summary": "High growth and margins; valuation elevated vs peers on headline multiples.",
            },
            "risk_factors": ["High valuation", "Concentration risk"],
            "highlights": ["AI leadership", "Data center growth"],
        }
        report = FundamentalReport.model_validate(data)
        dumped = report.model_dump(mode="json")
        assert dumped["ticker"] == "NVDA"
        assert dumped["profitability"]["gross_margin"] == 0.73
        assert "valuation elevated" in dumped["intelligence_overview"]["summary"]
        assert len(dumped["risk_factors"]) == 2


class TestSynthesisJsonExtraction:
    def test_extract_json_block(self):
        from app.agents.synthesis import _extract_json_block

        text = 'Some analysis text\n```json\n{"ticker": "AAPL"}\n```\nMore text'
        result = _extract_json_block(text)
        assert result is not None
        assert result["ticker"] == "AAPL"

    def test_extract_bare_json(self):
        from app.agents.synthesis import _extract_json_block

        text = 'Analysis: {"ticker": "NVDA", "company_name": "NVIDIA"}'
        result = _extract_json_block(text)
        assert result is not None
        assert result["ticker"] == "NVDA"

    def test_no_json_returns_none(self):
        from app.agents.synthesis import _extract_json_block

        result = _extract_json_block("Just plain text, no JSON here.")
        assert result is None
