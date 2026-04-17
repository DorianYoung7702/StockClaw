"""Chroma vector store: session-scoped RAG over deep fundamental documents (e.g. filings)."""

from __future__ import annotations

import logging
import uuid
from functools import lru_cache
from typing import TYPE_CHECKING, Optional

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings
from app.memory.embeddings import get_embeddings

if TYPE_CHECKING:
    from langchain_chroma import Chroma

logger = logging.getLogger(__name__)

COLLECTION_NAME = "atlas_fundamental"
# User- or API-ingested 10-K / annual report / MD&A text — not rendered agent output.
SOURCE_DEEP_FILING = "fundamental_deep_document"


@lru_cache(maxsize=1)
def _get_chroma_store() -> Optional["Chroma"]:
    """Singleton Chroma store; None if embeddings unavailable."""
    emb = get_embeddings()
    if emb is None:
        return None
    settings = get_settings()
    settings.ensure_chroma_persist_dir()

    from langchain_chroma import Chroma

    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=emb,
        persist_directory=str(settings.chroma_persist_directory),
    )


def ingest_fundamental_deep_documents(
    text: str,
    *,
    session_id: str,
    ticker: str,
    doc_label: str = "",
) -> None:
    """Chunk and embed listing filings / deep fundamental text (same session + ticker).

    Call this after the client uploads 10-K excerpts, annual report text, etc.
    Retrieval feeds the gather + synthesis steps for qualitative depth (MD&A, risks, segments).
    """
    settings = get_settings()
    if not settings.fundamental_rag_enabled:
        return
    store = _get_chroma_store()
    if store is None:
        logger.debug("Fundamental RAG ingest skipped: no embedding backend.")
        return
    body = (text or "").strip()
    if not body:
        return

    splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=150)
    chunks = splitter.split_text(body)
    max_chunks = settings.fundamental_rag_max_chunks_per_ingest
    if len(chunks) > max_chunks:
        chunks = chunks[:max_chunks]
        logger.warning("Fundamental RAG ingest truncated to %s chunks", max_chunks)

    label = (doc_label or "deep_filing").strip() or "deep_filing"
    docs: list[Document] = []
    for ch in chunks:
        docs.append(
            Document(
                page_content=ch,
                metadata={
                    "session_id": session_id,
                    "ticker": ticker or "",
                    "source": SOURCE_DEEP_FILING,
                    "doc_label": label,
                    "chunk_id": uuid.uuid4().hex,
                },
            )
        )
    try:
        store.add_documents(docs)
    except Exception as exc:
        logger.warning("Fundamental RAG ingest failed (non-fatal): %s", exc)


def retrieve_fundamental_context(
    query: str,
    *,
    session_id: str,
    ticker: Optional[str] = None,
) -> str:
    """Similarity search over ingested deep filings in the same session; optional ticker filter."""
    settings = get_settings()
    if not settings.fundamental_rag_enabled:
        return ""
    store = _get_chroma_store()
    if store is None:
        return ""
    q = (query or "").strip()
    if not q:
        return ""

    k = max(1, settings.fundamental_rag_top_k)
    try:
        # Chroma compound filters vary by version; filter session in DB, rest in-process.
        raw = store.similarity_search(
            q,
            k=max(k * 4, k),
            filter={"session_id": session_id},
        )
    except Exception as exc:
        logger.warning("Fundamental RAG retrieve failed: %s", exc)
        return ""

    docs: list[Document] = []
    for d in raw:
        if d.metadata.get("source") != SOURCE_DEEP_FILING:
            continue
        if ticker:
            mt = (d.metadata.get("ticker") or "")
            if mt and mt != ticker:
                continue
        docs.append(d)
        if len(docs) >= k:
            break

    if not docs:
        return ""

    parts = []
    for i, d in enumerate(docs, 1):
        parts.append(f"[{i}] {d.page_content}")
    return "\n\n".join(parts)


def clear_chroma_cache_for_tests() -> None:
    """Drop lru_cache for tests that toggle settings."""
    _get_chroma_store.cache_clear()
    try:
        from app.memory import embeddings as emb_mod

        emb_mod.get_embeddings.cache_clear()
    except Exception:
        pass
