"""Embedding model factory for fundamental RAG (OpenAI-compatible API)."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Optional

from app.config import get_settings

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings


@lru_cache(maxsize=1)
def get_embeddings() -> Optional["Embeddings"]:
    """Return embeddings for Chroma, or None if RAG is disabled or not configured."""
    settings = get_settings()
    if not settings.fundamental_rag_enabled:
        return None
    key = (settings.embedding_api_key or "").strip()
    if not key:
        return None

    from langchain_openai import OpenAIEmbeddings

    kwargs: dict = {
        "model": settings.embedding_model,
        "api_key": key,
    }
    if settings.embedding_base_url:
        kwargs["base_url"] = settings.embedding_base_url
    return OpenAIEmbeddings(**kwargs)


def embeddings_available() -> bool:
    """True when fundamental RAG can run (enabled + API key present)."""
    return get_embeddings() is not None
