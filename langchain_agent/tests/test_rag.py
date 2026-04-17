"""Tests for fundamental RAG helpers (mocked vector store / settings)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage


def test_retrieve_fundamental_rag_node_disabled():
    from app.agents.nodes import retrieve_fundamental_rag_node

    async def _run():
        with patch("app.agents.nodes.get_settings") as gs:
            gs.return_value = MagicMock(fundamental_rag_enabled=False)
            state = {
                "messages": [HumanMessage(content="follow up")],
                "session_id": "s1",
                "tickers": ["AAPL"],
                "resolved_symbol": "AAPL",
            }
            return await retrieve_fundamental_rag_node(state)

    out = asyncio.run(_run())
    assert out["retrieved_fundamental_context"] == ""
    assert "skipped" in out["current_step"]


def test_retrieve_fundamental_rag_node_returns_context():
    from app.agents.nodes import retrieve_fundamental_rag_node

    async def _run():
        with patch("app.agents.nodes.get_settings") as gs:
            gs.return_value = MagicMock(fundamental_rag_enabled=True)
            with patch("app.agents.nodes.retrieve_fundamental_context", return_value="[1] prior chunk"):
                state = {
                    "messages": [HumanMessage(content="compare to last quarter")],
                    "session_id": "sess-abc",
                    "tickers": ["MSFT"],
                    "resolved_symbol": "MSFT",
                }
                return await retrieve_fundamental_rag_node(state)

    out = asyncio.run(_run())
    assert "[1] prior chunk" in out["retrieved_fundamental_context"]


def test_ingest_skips_when_disabled(monkeypatch):
    import app.config as cfg

    monkeypatch.setenv("RAG_FUNDAMENTAL_ENABLED", "false")
    cfg._settings = None
    from app.memory.vector_store import ingest_fundamental_deep_documents

    ingest_fundamental_deep_documents("hello world", session_id="s", ticker="X")


def test_retrieve_empty_without_embeddings(monkeypatch):
    import app.config as cfg

    monkeypatch.setenv("RAG_FUNDAMENTAL_ENABLED", "true")
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg._settings = None
    from app.memory.vector_store import clear_chroma_cache_for_tests, retrieve_fundamental_context

    clear_chroma_cache_for_tests()
    out = retrieve_fundamental_context("query", session_id="sid", ticker="AAPL")
    assert out == ""
