"""Unit tests for individual LangChain tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


class TestFinancialStatementsTool:
    """Tests for the get_financial_statements tool."""

    @patch("app.tools.financial_statements._fetch_via_openbb")
    @patch("app.tools.financial_statements._fetch_via_yfinance")
    def test_returns_json_on_success(self, mock_yf, mock_obb):
        from app.tools.financial_statements import get_financial_statements

        mock_obb.return_value = [
            {"period": "2024", "revenue": 100_000_000, "net_income": 20_000_000}
        ]
        result = get_financial_statements.invoke(
            {"symbol": "AAPL", "statement_type": "income", "period": "annual", "limit": 4}
        )
        data = json.loads(result)
        assert isinstance(data, list)
        assert data[0]["revenue"] == 100_000_000
        mock_yf.assert_not_called()

    @patch("app.tools.financial_statements._fetch_via_openbb")
    @patch("app.tools.financial_statements._fetch_via_yfinance")
    def test_falls_back_to_yfinance(self, mock_yf, mock_obb):
        from app.tools.financial_statements import get_financial_statements

        mock_obb.return_value = []
        mock_yf.return_value = [{"period": "2024", "revenue": 50_000}]
        result = get_financial_statements.invoke(
            {"symbol": "AAPL", "statement_type": "income", "period": "annual", "limit": 4}
        )
        data = json.loads(result)
        assert data[0]["revenue"] == 50_000

    @patch("app.tools.financial_statements._fetch_via_openbb")
    @patch("app.tools.financial_statements._fetch_via_yfinance")
    def test_returns_error_when_all_fail(self, mock_yf, mock_obb):
        from app.tools.financial_statements import get_financial_statements

        mock_obb.return_value = []
        mock_yf.return_value = []
        result = get_financial_statements.invoke(
            {"symbol": "INVALID", "statement_type": "income", "period": "annual", "limit": 4}
        )
        data = json.loads(result)
        assert "error" in data


class TestKeyMetricsTool:
    """Tests for the get_key_metrics tool."""

    @patch("app.tools.key_metrics._fetch_metrics_openbb")
    @patch("app.tools.key_metrics._fetch_metrics_yfinance")
    def test_merges_sources(self, mock_yf, mock_obb):
        from app.tools.key_metrics import get_key_metrics

        mock_obb.return_value = {"pe_ratio": 25.0}
        mock_yf.return_value = {"pe_ratio": 25.0, "roe": 0.35}
        result = get_key_metrics.invoke({"symbol": "AAPL"})
        data = json.loads(result)
        assert data["pe_ratio"] == 25.0
        assert data["roe"] == 0.35


class TestCompanyProfileTool:
    """Tests for the get_company_profile tool."""

    @patch("app.tools.company_profile._fetch_profile")
    def test_returns_profile(self, mock_fetch):
        from app.tools.company_profile import get_company_profile

        mock_fetch.return_value = {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "industry": "Consumer Electronics",
        }
        result = get_company_profile.invoke({"symbol": "AAPL"})
        data = json.loads(result)
        assert data["name"] == "Apple Inc."


class TestCompanyNewsTool:
    """Tests for the get_company_news tool."""

    @patch("app.tools.news_sentiment._fetch_news")
    def test_returns_news_items(self, mock_fetch):
        from app.tools.news_sentiment import get_company_news

        mock_fetch.return_value = [
            {"title": "Apple reports record earnings", "url": "https://example.com"}
        ]
        result = get_company_news.invoke({"symbol": "AAPL", "limit": 5})
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 1
