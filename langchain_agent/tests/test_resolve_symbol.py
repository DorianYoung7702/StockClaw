"""Tests for the resolve_symbol node."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage


class TestResolveSymbolNode:
    @pytest.mark.asyncio
    @patch("app.agents.nodes.get_tool_calling_llm")
    @patch("app.agents.nodes._yf_search")
    @patch("app.providers.ticker_cache.get_yf_info")
    async def test_resolves_chinese_company_name(self, mock_get_info, mock_yf_search, mock_llm_factory):
        from app.agents.nodes import resolve_symbol_node

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='{"resolved": [{"input": "英伟达", "ticker": "NVDA"}]}'
        )
        mock_llm_factory.return_value = mock_llm

        mock_get_info.return_value = {"regularMarketPrice": 135.0, "shortName": "NVIDIA Corp"}
        mock_yf_search.return_value = []

        state = {
            "tickers": ["英伟达"],
            "errors": [],
            "messages": [HumanMessage(content="分析英伟达")],
        }
        result = await resolve_symbol_node(state)
        assert result["resolved_symbol"] == "NVDA"
        assert "NVDA" in result["tickers"]
        assert result["ticker_names"]["NVDA"] == "NVIDIA Corp"

    @pytest.mark.asyncio
    @patch("app.providers.ticker_cache.get_yf_info")
    async def test_keeps_valid_ticker_as_is(self, mock_get_info):
        from app.agents.nodes import resolve_symbol_node

        mock_get_info.return_value = {"regularMarketPrice": 195.0, "shortName": "Apple Inc."}
        state = {"tickers": ["AAPL"], "errors": []}
        result = await resolve_symbol_node(state)
        assert result["resolved_symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_empty_tickers_returns_error(self):
        from app.agents.nodes import resolve_symbol_node

        state = {"tickers": [], "errors": []}
        result = await resolve_symbol_node(state)
        assert result["resolved_symbol"] == ""
        assert any("No ticker" in e for e in result["errors"])

    @pytest.mark.asyncio
    @patch("app.agents.nodes.get_tool_calling_llm")
    @patch("app.agents.nodes._yf_search")
    @patch("app.providers.ticker_cache.get_yf_info")
    async def test_yf_search_fallback_for_chinese_name(self, mock_get_info, mock_yf_search, mock_llm_factory):
        """When LLM returns a Chinese company name as-is, yf.Search resolves it."""
        from app.agents.nodes import resolve_symbol_node

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='{"resolved": [{"input": "歌礼制药", "ticker": "歌礼制药"}]}'
        )
        mock_llm_factory.return_value = mock_llm

        mock_yf_search.return_value = [
            {"symbol": "2595.HK", "name": "GENFLEET-B", "exchange": "HKG"}
        ]
        mock_get_info.return_value = {"regularMarketPrice": 3.5, "shortName": "GENFLEET-B"}

        state = {
            "tickers": ["歌礼制药"],
            "errors": [],
            "messages": [HumanMessage(content="分析歌礼制药")],
        }
        result = await resolve_symbol_node(state)
        assert result["resolved_symbol"] == "2595.HK"
        assert "2595.HK" in result["tickers"]
        assert result["ticker_names"]["2595.HK"] == "GENFLEET-B"

    @pytest.mark.asyncio
    @patch("app.agents.nodes._yf_search")
    @patch("app.providers.ticker_cache.get_yf_info")
    async def test_yf_search_fallback_for_english_name(self, mock_get_info, mock_yf_search):
        """When user types an English company name like 'Genfleet', yf.Search resolves it."""
        from app.agents.nodes import resolve_symbol_node

        mock_yf_search.return_value = [
            {"symbol": "2595.HK", "name": "GENFLEET-B", "exchange": "HKG"}
        ]
        mock_get_info.return_value = {"regularMarketPrice": 3.5, "shortName": "GENFLEET-B"}

        state = {
            "tickers": ["Genfleet"],
            "errors": [],
            "messages": [HumanMessage(content="analyze Genfleet")],
        }
        result = await resolve_symbol_node(state)
        assert result["resolved_symbol"] == "2595.HK"
        assert "2595.HK" in result["tickers"]
        assert result["ticker_names"]["2595.HK"] == "GENFLEET-B"

    @pytest.mark.asyncio
    @patch("app.agents.nodes.get_tool_calling_llm")
    @patch("app.agents.nodes._yf_search")
    @patch("app.agents.nodes.adispatch_custom_event")
    async def test_resolve_fail_when_name_not_found(self, mock_dispatch, mock_yf_search, mock_llm_factory):
        """When LLM + yf.Search both fail, resolve_fail event is emitted and resolved_symbol is empty."""
        from app.agents.nodes import resolve_symbol_node

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='{"resolved": [{"input": "某某公司", "ticker": "某某公司"}]}'
        )
        mock_llm_factory.return_value = mock_llm

        # yf.Search returns nothing
        mock_yf_search.return_value = []

        state = {
            "tickers": ["某某公司"],
            "errors": [],
            "messages": [HumanMessage(content="分析某某公司")],
        }
        result = await resolve_symbol_node(state)
        assert result["resolved_symbol"] == ""
        assert len(result["tickers"]) == 0
        # resolve_fail event was dispatched
        mock_dispatch.assert_any_call("resolve_fail", {
            "query": "某某公司",
            "message": "未能识别「某某公司」对应的标的，请直接输入股票代码（如 2595.HK、AAPL）",
        })
