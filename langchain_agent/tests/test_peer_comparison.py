"""Tests for the peer_comparison tool."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


class TestPeerComparisonTool:
    @patch("app.tools.peer_comparison._get_peer_symbols")
    @patch("app.tools.peer_comparison._fetch_peer_metrics")
    def test_returns_comparison_data(self, mock_fetch, mock_peers):
        from app.tools.peer_comparison import get_peer_comparison

        mock_peers.return_value = ["MSFT", "GOOGL"]
        mock_fetch.return_value = [
            {"symbol": "AAPL", "name": "Apple", "pe_ratio": 32.0, "roe": 1.47},
            {"symbol": "MSFT", "name": "Microsoft", "pe_ratio": 35.0, "roe": 0.40},
            {"symbol": "GOOGL", "name": "Alphabet", "pe_ratio": 25.0, "roe": 0.28},
        ]

        result = get_peer_comparison.invoke({"symbol": "AAPL", "max_peers": 5})
        data = json.loads(result)
        assert data["target"]["symbol"] == "AAPL"
        assert len(data["peers"]) == 2

    @patch("app.tools.peer_comparison._get_peer_symbols")
    def test_no_peers_returns_error(self, mock_peers):
        from app.tools.peer_comparison import get_peer_comparison

        mock_peers.return_value = []
        result = get_peer_comparison.invoke({"symbol": "UNKNOWN", "max_peers": 5})
        data = json.loads(result)
        assert "error" in data
