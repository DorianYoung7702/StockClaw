"""Tests for the risk_metrics tool."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


class TestRiskMetricsTool:
    @patch("yfinance.Ticker")
    def test_returns_risk_data(self, mock_yf_class):
        from app.tools.risk_metrics import get_risk_metrics

        mock_ticker = MagicMock()
        mock_ticker.info = {
            "beta": 1.2,
            "shortRatio": 2.5,
            "shortPercentOfFloat": 0.015,
            "fiftyTwoWeekHigh": 200.0,
            "fiftyTwoWeekLow": 150.0,
            "currentPrice": 195.0,
        }
        mock_ticker.insider_transactions = None
        mock_yf_class.return_value = mock_ticker

        with patch("app.tools.risk_metrics._compute_volatility", return_value=0.25):
            result = get_risk_metrics.invoke({"symbol": "AAPL"})
            data = json.loads(result)
            assert data["beta"] == 1.2
            assert data["annualised_volatility"] == 0.25
            assert data["pct_from_52w_high"] is not None
