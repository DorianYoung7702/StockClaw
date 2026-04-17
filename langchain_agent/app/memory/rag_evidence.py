from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Optional

from langchain_core.documents import Document

from app.config import get_settings
from app.memory.embeddings import get_embeddings
from app.memory.vector_store import COLLECTION_NAME as FUNDAMENTAL_COLLECTION_NAME
from app.memory.vector_store import SOURCE_DEEP_FILING

if TYPE_CHECKING:
    from langchain_chroma import Chroma

SOURCE_NEWS_EVENT = "news_event"
NEWS_COLLECTION_NAME = "atlas_news_events"


@lru_cache(maxsize=4)
def _get_chroma_store(collection_name: str) -> Optional["Chroma"]:
    emb = get_embeddings()
    if emb is None:
        return None
    settings = get_settings()
    settings.ensure_chroma_persist_dir()

    from langchain_chroma import Chroma

    return Chroma(
        collection_name=collection_name,
        embedding_function=emb,
        persist_directory=str(settings.chroma_persist_directory),
    )


def _safe_text(value: Any, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _safe_score(value: Any) -> float | None:
    try:
        score = float(value)
    except Exception:
        return None
    return round(score, 4)


def _search(
    *,
    collection_name: str,
    query: str,
    session_id: str,
    raw_k: int,
) -> list[tuple[Document, float | None]]:
    store = _get_chroma_store(collection_name)
    if store is None:
        return []

    try:
        rows = store.similarity_search_with_relevance_scores(
            query,
            k=raw_k,
            filter={"session_id": session_id},
        )
        return [(doc, _safe_score(score)) for doc, score in rows]
    except Exception:
        pass

    try:
        rows = store.similarity_search_with_score(
            query,
            k=raw_k,
            filter={"session_id": session_id},
        )
        return [(doc, _safe_score(score)) for doc, score in rows]
    except Exception:
        pass

    try:
        rows = store.similarity_search(
            query,
            k=raw_k,
            filter={"session_id": session_id},
        )
        return [(doc, None) for doc in rows]
    except Exception:
        return []


def _render_context(items: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for idx, item in enumerate(items, 1):
        title = item.get("title") or item.get("source_label") or item.get("source_type") or "Evidence"
        label = item.get("source_label") or item.get("source_type") or "source"
        published = item.get("published_at") or ""
        snippet = item.get("snippet") or ""
        meta = f" | {label}" if label else ""
        if published:
            meta += f" | {published}"
        blocks.append(f"[{idx}] {title}{meta}\n{snippet}")
    return "\n\n".join(blocks)


def retrieve_fundamental_evidence(
    query: str,
    *,
    session_id: str,
    ticker: Optional[str] = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.fundamental_rag_enabled:
        return {
            "items": [],
            "context": "",
            "debug": {"status": "disabled", "query": query, "top_k": settings.fundamental_rag_top_k, "hit_count": 0},
        }

    q = (query or "").strip()
    if not q:
        return {"items": [], "context": "", "debug": {"status": "empty_query", "query": q, "top_k": settings.fundamental_rag_top_k, "hit_count": 0}}

    top_k = max(1, settings.fundamental_rag_top_k)
    rows = _search(
        collection_name=FUNDAMENTAL_COLLECTION_NAME,
        query=q,
        session_id=session_id,
        raw_k=max(top_k * 4, top_k),
    )

    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for doc, score in rows:
        if doc.metadata.get("source") != SOURCE_DEEP_FILING:
            continue
        if ticker:
            item_ticker = str(doc.metadata.get("ticker") or "")
            if item_ticker and item_ticker != ticker:
                continue
        dedupe_key = str(doc.metadata.get("chunk_id") or hashlib.md5(doc.page_content.encode("utf-8", errors="ignore")).hexdigest())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        doc_label = str(doc.metadata.get("doc_label") or "deep_filing")
        item_ticker = str(doc.metadata.get("ticker") or ticker or "")
        items.append({
            "id": dedupe_key,
            "source_type": "filing",
            "source_label": doc_label,
            "ticker": item_ticker,
            "title": f"{item_ticker or '财报'} · {doc_label}",
            "snippet": _safe_text(doc.page_content),
            "score": score,
            "published_at": None,
            "url": None,
            "doc_label": doc_label,
            "metadata": {
                "chunk_id": doc.metadata.get("chunk_id"),
                "session_id": doc.metadata.get("session_id"),
            },
        })
        if len(items) >= top_k:
            break

    return {
        "items": items,
        "context": _render_context(items),
        "debug": {
            "status": "ok" if items else "empty",
            "query": q,
            "top_k": top_k,
            "hit_count": len(items),
            "scope": "session",
            "ticker": ticker or "",
            "source_distribution": {"filing": len(items)},
        },
    }


def ingest_news_event_documents(
    items: list[dict[str, Any]],
    *,
    session_id: str,
    ticker: str,
) -> None:
    settings = get_settings()
    if not settings.fundamental_rag_enabled:
        return
    store = _get_chroma_store(NEWS_COLLECTION_NAME)
    if store is None:
        return

    docs: list[Document] = []
    for item in items:
        title = str(item.get("title") or "")
        summary = str(item.get("summary") or "")
        if not title and not summary:
            continue
        url = str(item.get("url") or "")
        published = str(item.get("published") or item.get("published_at") or "")
        source_label = str(item.get("source") or "news")
        body = "\n".join(part for part in [title, summary, source_label, published] if part)
        raw_id = f"{ticker}|{title}|{url}|{published}".encode("utf-8", errors="ignore")
        event_id = hashlib.md5(raw_id).hexdigest()
        docs.append(
            Document(
                page_content=body,
                metadata={
                    "session_id": session_id,
                    "ticker": ticker or "",
                    "source": SOURCE_NEWS_EVENT,
                    "event_id": event_id,
                    "title": title,
                    "url": url,
                    "published": published,
                    "source_label": source_label,
                    "summary": summary,
                },
            )
        )
    if not docs:
        return
    try:
        store.add_documents(docs)
    except Exception:
        return


def retrieve_news_evidence(
    query: str,
    *,
    session_id: str,
    ticker: Optional[str] = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.fundamental_rag_enabled:
        return {
            "items": [],
            "context": "",
            "debug": {"status": "disabled", "query": query, "top_k": settings.fundamental_rag_top_k, "hit_count": 0},
        }

    q = (query or "").strip()
    if not q:
        return {"items": [], "context": "", "debug": {"status": "empty_query", "query": q, "top_k": settings.fundamental_rag_top_k, "hit_count": 0}}

    top_k = max(1, min(5, settings.fundamental_rag_top_k))
    rows = _search(
        collection_name=NEWS_COLLECTION_NAME,
        query=q,
        session_id=session_id,
        raw_k=max(top_k * 4, top_k),
    )

    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    source_distribution: dict[str, int] = {}
    for doc, score in rows:
        if doc.metadata.get("source") != SOURCE_NEWS_EVENT:
            continue
        if ticker:
            item_ticker = str(doc.metadata.get("ticker") or "")
            if item_ticker and item_ticker != ticker:
                continue
        event_id = str(doc.metadata.get("event_id") or hashlib.md5(doc.page_content.encode("utf-8", errors="ignore")).hexdigest())
        if event_id in seen:
            continue
        seen.add(event_id)
        source_label = str(doc.metadata.get("source_label") or "news")
        source_distribution[source_label] = source_distribution.get(source_label, 0) + 1
        item_ticker = str(doc.metadata.get("ticker") or ticker or "")
        items.append({
            "id": event_id,
            "source_type": "news",
            "source_label": source_label,
            "ticker": item_ticker,
            "title": str(doc.metadata.get("title") or f"{item_ticker} 新闻事件"),
            "snippet": _safe_text(doc.metadata.get("summary") or doc.page_content),
            "score": score,
            "published_at": str(doc.metadata.get("published") or "") or None,
            "url": str(doc.metadata.get("url") or "") or None,
            "doc_label": None,
            "metadata": {
                "session_id": doc.metadata.get("session_id"),
            },
        })
        if len(items) >= top_k:
            break

    return {
        "items": items,
        "context": _render_context(items),
        "debug": {
            "status": "ok" if items else "empty",
            "query": q,
            "top_k": top_k,
            "hit_count": len(items),
            "scope": "session",
            "ticker": ticker or "",
            "source_distribution": source_distribution,
        },
    }
