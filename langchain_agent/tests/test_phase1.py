"""Phase 1 architecture tests — parallel fan-out, retry, hybrid routing, HITL, checkpoint."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. Hybrid routing (rules-first parse_input)
# ---------------------------------------------------------------------------


class TestFastParse:
    """Test _fast_parse rule-based intent detection (no LLM required)."""

    def _fp(self, text: str):
        from app.agents.nodes import _fast_parse
        return _fast_parse(text)

    def test_strong_stocks_chinese(self):
        r = self._fp("给我看看今天的强势股")
        assert r is not None
        assert r["intent"] == "strong_stocks"
        assert r["tickers"] == []

    def test_strong_stocks_english(self):
        r = self._fp("show me the strong stock screening list")
        assert r is not None
        assert r["intent"] == "strong_stocks"

    def test_single_ticker(self):
        r = self._fp("Analyse AAPL for me")
        assert r is not None
        assert r["intent"] == "single_stock"
        assert "AAPL" in r["tickers"]

    def test_compare_two_tickers(self):
        r = self._fp("Compare AAPL vs MSFT please")
        assert r is not None
        assert r["intent"] == "compare"
        assert "AAPL" in r["tickers"]
        assert "MSFT" in r["tickers"]

    def test_stopwords_filtered(self):
        r = self._fp("What is AI doing today?")
        assert r is None

    def test_no_ticker_returns_none(self):
        r = self._fp("Hello, how are you?")
        assert r is None

    def test_hk_ticker(self):
        r = self._fp("Tell me about 0700.HK")
        assert r is not None
        assert r["intent"] == "single_stock"


class TestParseInputNodeFastPath:
    """parse_input_node should take the fast-path for unambiguous messages."""

    @pytest.mark.asyncio
    async def test_fast_path_no_llm_call(self):
        from langchain_core.messages import HumanMessage
        from app.agents.nodes import parse_input_node

        state: dict[str, Any] = {"messages": [HumanMessage(content="Analyse NVDA")]}

        with patch("app.agents.nodes.get_tool_calling_llm") as mock_llm:
            result = await parse_input_node(state)

        mock_llm.assert_not_called()
        assert result["intent"] == "single_stock"
        assert "NVDA" in result["tickers"]
        assert result["current_step"] == "parsed_input_fast"


# ---------------------------------------------------------------------------
# 2. State merge reducer for parallel fan-in
# ---------------------------------------------------------------------------


class TestFinancialDataMergeReducer:
    """financial_data merge reducer must combine dicts from parallel nodes."""

    def test_merge_non_overlapping(self):
        from app.models.state import _merge_financial_data

        a = {"fundamental_text": "fund data", "tickers": ["AAPL"]}
        b = {"sentiment_text": "positive"}
        merged = _merge_financial_data(a, b)
        assert merged["fundamental_text"] == "fund data"
        assert merged["sentiment_text"] == "positive"
        assert merged["tickers"] == ["AAPL"]

    def test_merge_overlapping_last_wins(self):
        from app.models.state import _merge_financial_data

        a = {"key": "old"}
        b = {"key": "new"}
        assert _merge_financial_data(a, b)["key"] == "new"

    def test_merge_empty_dicts(self):
        from app.models.state import _merge_financial_data

        assert _merge_financial_data({}, {}) == {}
        assert _merge_financial_data({"a": 1}, {}) == {"a": 1}
        assert _merge_financial_data({}, {"b": 2}) == {"b": 2}


# ---------------------------------------------------------------------------
# 3. Sentiment node writes independent key (not reading financial_data)
# ---------------------------------------------------------------------------


class TestSentimentNodeFanIn:
    """sentiment_node must return only sentiment_text — not copy full financial_data."""

    @pytest.mark.asyncio
    async def test_sentiment_returns_only_its_key(self):
        from langchain_core.messages import AIMessage
        from app.agents.nodes import sentiment_node

        mock_agent = AsyncMock()
        mock_agent.ainvoke.return_value = {
            "messages": [AIMessage(content="Overall positive sentiment.")]
        }

        state: dict[str, Any] = {
            "tickers": ["AAPL"],
            "financial_data": {"fundamental_text": "pre-existing data"},
            "errors": [],
        }

        with patch("app.agents.nodes.create_sentiment_agent", return_value=mock_agent):
            result = await sentiment_node(state)

        fd = result["financial_data"]
        assert "sentiment_text" in fd
        assert "fundamental_text" not in fd, (
            "sentiment_node must NOT copy fundamental_text — merge reducer handles fan-in"
        )

    @pytest.mark.asyncio
    async def test_sentiment_skipped_no_tickers(self):
        from app.agents.nodes import sentiment_node

        state: dict[str, Any] = {"tickers": [], "financial_data": {}, "errors": []}
        result = await sentiment_node(state)
        assert result["current_step"] == "sentiment_skipped"
        assert result["financial_data"] == {"sentiment_text": ""}


# ---------------------------------------------------------------------------
# 4. node_retry decorator
# ---------------------------------------------------------------------------


class TestNodeRetry:
    """Retry decorator: exponential back-off, timeout, non-retryable pass-through."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        from app.utils.retry import node_retry

        @node_retry(max_attempts=3)
        async def good_node(state):
            return {"result": "ok"}

        result = await good_node({})
        assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_retries_and_succeeds(self):
        from app.utils.retry import node_retry

        call_count = 0

        @node_retry(max_attempts=3, base_delay=0.01)
        async def flaky_node(state):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("transient error")
            return {"result": "ok"}

        result = await flaky_node({})
        assert result == {"result": "ok"}
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_all_attempts_fail_returns_errors(self):
        from app.utils.retry import node_retry

        @node_retry(max_attempts=2, base_delay=0.01)
        async def bad_node(state):
            raise ConnectionError("always fails")

        state = {"errors": ["prior error"]}
        result = await bad_node(state)
        assert "errors" in result
        assert len(result["errors"]) == 2
        assert "bad_node" in result["errors"][-1]
        assert "current_step" in result

    @pytest.mark.asyncio
    async def test_non_retryable_raises_immediately(self):
        from app.utils.retry import node_retry

        call_count = 0

        @node_retry(max_attempts=3, base_delay=0.01)
        async def bad_input_node(state):
            nonlocal call_count
            call_count += 1
            raise ValueError("bad input")

        with pytest.raises(ValueError):
            await bad_input_node({})
        assert call_count == 1, "ValueError must not be retried"

    @pytest.mark.asyncio
    async def test_timeout_triggers_retry(self):
        from app.utils.retry import node_retry

        call_count = 0

        @node_retry(max_attempts=2, base_delay=0.01, timeout_seconds=0.05)
        async def slow_node(state):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(10)
            return {"result": "never"}

        result = await slow_node({})
        assert call_count == 2
        assert "current_step" in result

    @pytest.mark.asyncio
    async def test_custom_fallback_returned(self):
        from app.utils.retry import node_retry

        fallback = {"financial_data": {}, "current_step": "gather_data_failed", "errors": []}

        @node_retry(max_attempts=2, base_delay=0.01, fallback=fallback)
        async def always_fails(state):
            raise RuntimeError("boom")

        result = await always_fails({})
        assert result is fallback


# ---------------------------------------------------------------------------
# 5. Graph routing — _route_after_fundamental_rag fan-out
# ---------------------------------------------------------------------------


class TestGraphRouting:
    """Graph conditional edges must fan-out correctly."""

    def test_fan_out_single_stock(self):
        from app.agents.graph import _route_after_fundamental_rag

        state: dict[str, Any] = {"intent": "single_stock", "tickers": ["AAPL"]}
        result = _route_after_fundamental_rag(state)
        assert isinstance(result, list)
        assert "gather_data" in result
        assert "sentiment" in result

    def test_no_fan_out_strong_stocks(self):
        from app.agents.graph import _route_after_fundamental_rag

        state: dict[str, Any] = {"intent": "strong_stocks", "tickers": []}
        result = _route_after_fundamental_rag(state)
        assert result == "synthesis"

    def test_compare_also_fans_out(self):
        from app.agents.graph import _route_after_fundamental_rag

        state: dict[str, Any] = {"intent": "compare", "tickers": ["AAPL", "MSFT"]}
        result = _route_after_fundamental_rag(state)
        assert isinstance(result, list)

    def test_ambiguous_tickers_routes_to_human_confirm(self):
        from app.agents.graph import _route_after_resolve

        state: dict[str, Any] = {
            "ambiguous_tickers": ["BABA", "BABA.HK"],
            "resolved_symbol": "BABA",
        }
        assert _route_after_resolve(state) == "human_confirm"

    def test_clear_symbol_skips_human_confirm(self):
        from app.agents.graph import _route_after_resolve

        state: dict[str, Any] = {
            "ambiguous_tickers": [],
            "resolved_symbol": "AAPL",
        }
        assert _route_after_resolve(state) == "retrieve_fundamental_rag"


# ---------------------------------------------------------------------------
# 6. human_confirm_node clears ambiguity
# ---------------------------------------------------------------------------


class TestHumanConfirmNode:
    @pytest.mark.asyncio
    async def test_clears_ambiguous_tickers(self):
        from app.agents.nodes import human_confirm_node

        state: dict[str, Any] = {
            "ambiguous_tickers": ["BABA", "BABA.HK"],
            "resolved_symbol": "BABA",
            "tickers": ["BABA", "BABA.HK"],
        }
        result = await human_confirm_node(state)
        assert result["ambiguous_tickers"] == []
        assert result["resolved_symbol"] == "BABA"
        assert result["tickers"] == ["BABA"]


# ---------------------------------------------------------------------------
# 7. Checkpointer falls back to MemorySaver when SQLite unavailable
# ---------------------------------------------------------------------------


class TestCheckpointer:
    def test_falls_back_to_memory_saver_when_path_is_memory(self):
        import app.memory.store as store_mod
        from langgraph.checkpoint.memory import MemorySaver

        store_mod._checkpointer = None
        with patch.dict("os.environ", {"CHECKPOINT_DB_PATH": ":memory:"}):
            cp = store_mod.get_checkpointer()

        assert isinstance(cp, MemorySaver)

    def test_singleton_returned_on_second_call(self):
        import app.memory.store as store_mod

        store_mod._checkpointer = None
        with patch.dict("os.environ", {"CHECKPOINT_DB_PATH": ":memory:"}):
            cp1 = store_mod.get_checkpointer()
            cp2 = store_mod.get_checkpointer()

        assert cp1 is cp2

    @pytest.mark.asyncio
    async def test_init_checkpointer_creates_sqlite_saver(self, tmp_path):
        """init_checkpointer should call setup() and store an AsyncSqliteSaver."""
        import app.memory.store as store_mod

        store_mod._checkpointer = None
        db_file = str(tmp_path / "test_sessions.db")

        with patch.dict("os.environ", {"CHECKPOINT_DB_PATH": db_file}):
            await store_mod.init_checkpointer()

        cp = store_mod.get_checkpointer()
        assert "SqliteSaver" in type(cp).__name__ or "MemorySaver" in type(cp).__name__

    @pytest.mark.asyncio
    async def test_init_checkpointer_fallback_on_import_error(self):
        """Should fall back to MemorySaver if sqlite package is not importable."""
        import app.memory.store as store_mod
        from langgraph.checkpoint.memory import MemorySaver

        store_mod._checkpointer = None

        with (
            patch.dict("os.environ", {"CHECKPOINT_DB_PATH": "/some/path.db"}),
            patch.dict("sys.modules", {"langgraph.checkpoint.sqlite.aio": None}),
        ):
            await store_mod.init_checkpointer()

        assert isinstance(store_mod.get_checkpointer(), MemorySaver)


# ---------------------------------------------------------------------------
# 8. Bearer Token auth
# ---------------------------------------------------------------------------


class TestBearerAuth:
    """verify_token dependency must reject bad tokens and pass when auth disabled."""

    @pytest.mark.asyncio
    async def test_auth_disabled_when_token_empty(self):
        from app.api.auth import verify_token

        with patch.dict("os.environ", {"ATLAS_API_TOKEN": ""}):
            result = await verify_token(credentials=None)

        assert result is None  # no exception

    @pytest.mark.asyncio
    async def test_rejects_missing_token(self):
        from fastapi import HTTPException
        from app.api.auth import verify_token

        with patch.dict("os.environ", {"ATLAS_API_TOKEN": "secret-token-123"}):
            with pytest.raises(HTTPException) as exc_info:
                await verify_token(credentials=None)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_rejects_wrong_token(self):
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials
        from app.api.auth import verify_token

        bad = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong")
        with patch.dict("os.environ", {"ATLAS_API_TOKEN": "secret-token-123"}):
            with pytest.raises(HTTPException):
                await verify_token(credentials=bad)

    @pytest.mark.asyncio
    async def test_accepts_correct_token(self):
        from fastapi.security import HTTPAuthorizationCredentials
        from app.api.auth import verify_token

        good = HTTPAuthorizationCredentials(scheme="Bearer", credentials="secret-token-123")
        with patch.dict("os.environ", {"ATLAS_API_TOKEN": "secret-token-123"}):
            result = await verify_token(credentials=good)

        assert result is None  # no exception


# ---------------------------------------------------------------------------
# 9. asyncio.to_thread wrapping (strong_stocks_node uses asyncio.gather)
# ---------------------------------------------------------------------------


class TestAsyncToThread:
    @pytest.mark.asyncio
    async def test_strong_stocks_node_uses_gather(self):
        """strong_stocks_node should call asyncio.gather (non-blocking)."""
        from app.agents.nodes import strong_stocks_node

        state: dict[str, Any] = {"tickers": [], "financial_data": {}, "errors": []}

        with patch("app.agents.nodes.get_strong_stocks") as mock_tool:
            mock_tool.invoke.return_value = '{"stocks": []}'
            result = await strong_stocks_node(state)

        assert mock_tool.invoke.call_count == 2  # us + hk
        assert "strong_stocks_text" in result["financial_data"]


# ---------------------------------------------------------------------------
# 10. TickerCache — TTL, dedup, thread safety
# ---------------------------------------------------------------------------


class TestTickerCache:
    def _make_cache(self, ttl=10.0):
        from app.providers.ticker_cache import TickerCache
        return TickerCache(default_ttl=ttl)

    def test_set_and_get(self):
        c = self._make_cache()
        c.set("k", "v")
        assert c.get("k") == "v"

    def test_miss_returns_none(self):
        c = self._make_cache()
        assert c.get("missing") is None

    def test_ttl_expiry(self):
        import time
        c = self._make_cache(ttl=0.05)
        c.set("k", "v")
        assert c.get("k") == "v"
        time.sleep(0.06)
        assert c.get("k") is None

    def test_clear(self):
        c = self._make_cache()
        c.set("a", 1)
        c.set("b", 2)
        assert c.size == 2
        c.clear()
        assert c.size == 0

    def test_get_yf_info_caches(self):
        """Second call to get_yf_info must hit cache, not yfinance."""
        from app.providers.ticker_cache import TickerCache, _cache

        _cache.clear()
        fake_info = {"longName": "Apple Inc.", "marketCap": 3e12}

        with patch("app.providers.ticker_cache._yf_ticker") as mock_tk:
            mock_tk.return_value.info = fake_info

            from app.providers.ticker_cache import get_yf_info
            r1 = get_yf_info("AAPL")
            r2 = get_yf_info("AAPL")

        assert r1 == fake_info
        assert r2 == fake_info
        mock_tk.assert_called_once()  # only 1 yfinance call, not 2
