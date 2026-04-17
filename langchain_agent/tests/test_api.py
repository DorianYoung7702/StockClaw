"""End-to-end API tests using FastAPI TestClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from app.main import app
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "llm_provider" in data

    def test_health_checks_include_fundamental_rag_ready(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        checks = resp.json().get("checks", {})
        assert "fundamental_rag_ready" in checks
        assert isinstance(checks["fundamental_rag_ready"], bool)
        assert "llm_configured" in checks
        assert "openbb_module" in checks

    def test_root_returns_service_info(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "service" in data


class TestStrongStocksEndpoint:
    @patch("app.api.routes.get_strong_stocks")
    def test_strong_stocks_returns_list(self, mock_tool, client):
        mock_tool.invoke.return_value = (
            '{"market_type": "us_stock", "count": 1, '
            '"stocks": [{"symbol": "NVDA", "name": "NVIDIA"}]}'
        )
        resp = client.post("/api/v1/strong-stocks", json={"market_type": "us_stock"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["market_type"] == "us_stock"
        assert len(data["stocks"]) == 1


class TestChatEndpoint:
    @patch("app.dependencies.get_compiled_graph")
    def test_chat_non_streaming(self, mock_graph_fn, client):
        from langchain_core.messages import AIMessage, HumanMessage

        mock_graph = AsyncMock()
        mock_graph.ainvoke.return_value = {
            "messages": [
                HumanMessage(content="hello"),
                AIMessage(content="Hi! I'm Atlas, your financial assistant."),
            ]
        }
        mock_graph_fn.return_value = mock_graph

        resp = client.post("/api/v1/chat", json={"message": "hello", "stream": False})
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert "Atlas" in data["message"] or len(data["message"]) > 0


class TestAnalyzeEndpoint:
    @patch("app.dependencies.get_compiled_graph")
    def test_analyze_non_streaming(self, mock_graph_fn, client):
        from langchain_core.messages import AIMessage, HumanMessage

        mock_graph = AsyncMock()
        mock_graph.ainvoke.return_value = {
            "messages": [
                HumanMessage(content="Analyse AAPL"),
                AIMessage(content="# AAPL Fundamental Analysis\n\nApple Inc..."),
            ]
        }
        mock_graph_fn.return_value = mock_graph

        resp = client.post("/api/v1/analyze", json={"ticker": "AAPL", "stream": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert "AAPL" in data["report"]
