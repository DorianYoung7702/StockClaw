"""Shared pytest fixtures."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

# Ensure we don't hit real APIs during tests
os.environ.setdefault("LLM_PROVIDER", "minimax")
os.environ.setdefault("MINIMAX_API_KEY", "test-minimax-key-for-testing")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-key-for-testing")
os.environ.setdefault("OPENBB_TOKEN", "test-token")
os.environ.setdefault("CHECKPOINT_DB_PATH", ":memory:")
os.environ.setdefault("ATLAS_API_TOKEN", "")


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Reset the cached settings singleton between tests."""
    import app.config as cfg_mod
    cfg_mod._settings = None
    import app.memory.store as store_mod
    store_mod._checkpointer = None
    try:
        from app.memory.vector_store import clear_chroma_cache_for_tests

        clear_chroma_cache_for_tests()
    except Exception:
        pass
    yield
    cfg_mod._settings = None
    store_mod._checkpointer = None
    try:
        from app.memory.vector_store import clear_chroma_cache_for_tests

        clear_chroma_cache_for_tests()
    except Exception:
        pass


@pytest.fixture()
def mock_openbb():
    """Patch the openbb import to avoid requiring the full OpenBB installation."""
    mock_obb = MagicMock()
    with patch.dict("sys.modules", {"openbb": mock_obb}):
        yield mock_obb


@pytest.fixture()
def mock_yfinance():
    """Patch yfinance to return deterministic data."""
    mock_yf = MagicMock()
    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        yield mock_yf
