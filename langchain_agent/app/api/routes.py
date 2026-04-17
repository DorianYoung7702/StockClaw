"""FastAPI route definitions."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from app.api.auth import verify_token, get_current_user_id
from app.api import schemas
from app.context import current_user_id as _current_user_id_var
from pydantic import BaseModel, Field as PydanticField
from app.api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    ChatRequest,
    ChatResponse,
    FundamentalDocumentIngestRequest,
    FundamentalDocumentIngestResponse,
    HealthResponse,
    SingleStrongStockRequest,
    SingleStrongStockResponse,
    StrongStocksRequest,
    StrongStocksResponse,
    TaskCreateRequest,
    TaskListResponse,
    TaskResponse,
    TaskUpdateRequest,
    WatchlistAddRequest,
    WatchlistRemoveRequest,
    WatchlistUpdateRequest,
    WatchlistResponse,
)
from app.config import Settings
from app.memory.embeddings import embeddings_available
from app.dependencies import get_app_settings, get_compiled_graph, get_fresh_callbacks
from app.memory.store import make_thread_config
from app.memory.vector_store import ingest_fundamental_deep_documents
from app.tools.strong_stocks import load_single_strong_stock, load_strong_stocks_with_params

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Harness: UserStore helpers (fire-and-forget)
# ---------------------------------------------------------------------------

async def _upsert_user(user_id: str) -> None:
    """Track user login / session in UserStore (fire-and-forget)."""
    try:
        from app.harness.user_store import UserStore
        store = await UserStore.create()
        await store.upsert(user_id)
        await store.close()
    except Exception as exc:
        logger.debug("UserStore upsert failed (non-fatal): %s", exc)


async def _track_analysis(user_id: str) -> None:
    """Increment user's analysis counter (fire-and-forget)."""
    try:
        from app.harness.user_store import UserStore
        store = await UserStore.create()
        await store.upsert(user_id)
        await store.increment_analyses(user_id)
        await store.close()
    except Exception as exc:
        logger.debug("UserStore track_analysis failed (non-fatal): %s", exc)


async def _flush_journal_and_summarize(journal) -> None:
    """Flush RunJournal to DB, log summary, and trigger metrics check.

    Fire-and-forget: should be wrapped in asyncio.create_task().
    """
    try:
        await journal.flush()
        summary = journal.summary()
        logger.info(
            "RunJournal[%s]: duration=%.0fms tools=%d errors=%d recoveries=%s",
            summary.get("run_id", "?"),
            summary.get("duration_ms", 0),
            summary.get("tool_calls", 0),
            summary.get("errors", 0),
            summary.get("recovery_levels", []),
        )
    except Exception as exc:
        logger.debug("Journal flush/summary failed (non-fatal): %s", exc)


# Public routes (no auth) — health check for load balancers / probes
public_router = APIRouter(prefix="/api/v1")

# Protected routes — require Bearer token when ATLAS_API_TOKEN is set
router = APIRouter(prefix="/api/v1", dependencies=[Depends(verify_token)])


def _get_resident_agent_service(request: Request):
    service = getattr(request.app.state, "resident_agent_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Resident agent service unavailable")
    return service


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@public_router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_app_settings)):
    checks = {
        "llm_configured": bool(
            settings.minimax_api_key or settings.deepseek_api_key or settings.zhipu_api_key
        ),
        "monitor_module": settings.monitor_module_root.exists(),
        "fundamental_rag_ready": bool(
            settings.fundamental_rag_enabled and embeddings_available()
        ),
    }
    return HealthResponse(
        llm_provider=settings.llm_provider.value,
        checks=checks,
    )


# ---------------------------------------------------------------------------
# Explain — lightweight LLM streaming, no graph / tool routing
# ---------------------------------------------------------------------------


class ExplainRequest(BaseModel):
    prompt: str = PydanticField(description="Prompt to send to the LLM")


async def _stream_explain(prompt: str) -> AsyncGenerator[str, None]:
    """Stream LLM tokens directly without going through the LangGraph agent."""
    from app.llm.factory import get_tool_calling_llm

    llm = get_tool_calling_llm()
    think_filter = _ThinkFilter()
    async for chunk in llm.astream(prompt):
        if chunk.content:
            visible = think_filter.feed(chunk.content)
            if visible:
                payload = json.dumps({"type": "token", "content": visible}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
    tail = think_filter.flush()
    if tail:
        payload = json.dumps({"type": "token", "content": tail}, ensure_ascii=False)
        yield f"data: {payload}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/explain")
async def explain(req: ExplainRequest, user_id: str = Depends(get_current_user_id)):
    """Lightweight streaming LLM endpoint — no graph, no tools, no routing."""
    _current_user_id_var.set(user_id)
    return StreamingResponse(
        _stream_explain(req.prompt),
        media_type="text/event-stream",
    )


# ---------------------------------------------------------------------------
# Auth verification — used by frontend TokenGate to validate the API key
# ---------------------------------------------------------------------------

@router.get("/auth/verify")
async def verify_auth(
    user_id: str = Depends(get_current_user_id),
    credentials: HTTPAuthorizationCredentials | None = Security(HTTPBearer(auto_error=False)),
):
    """Return the caller's current auth identity once the Bearer token is verified."""
    from app.api.auth import is_admin_token

    token = credentials.credentials if credentials else ""
    return {
        "status": "ok",
        "user_id": user_id,
        "is_admin": is_admin_token(token),
    }


async def _run_llm_probe(body: schemas.LLMTestRequest) -> dict[str, object]:
    import time

    from app.harness.llm_config import LLM_PROVIDER_CATALOG
    from app.llm.factory import create_llm_from_config

    meta = LLM_PROVIDER_CATALOG.get(body.provider)
    if meta is None:
        raise HTTPException(400, f"Unknown LLM provider: {body.provider}")

    start = time.time()
    try:
        llm = create_llm_from_config(
            provider=body.provider,
            api_key=body.api_key,
            base_url=body.base_url,
            tool_calling_model=body.tool_calling_model or meta.default_tool_model,
            reasoning_model=body.reasoning_model or meta.default_reasoning_model,
            tool_calling_temperature=body.tool_calling_temperature,
            reasoning_temperature=body.reasoning_temperature,
            max_tokens=min(body.max_tokens, 512),
            role="tool_calling",
            model=body.tool_calling_model or meta.default_tool_model,
            temperature=body.tool_calling_temperature,
        )
        result = await llm.ainvoke([
            {"role": "system", "content": "Reply with exactly OK."},
            {"role": "user", "content": "ping"},
        ])
        content = getattr(result, "content", "")
        success = bool(content)
        latency = (time.time() - start) * 1000
        if success:
            return {"provider": body.provider, "success": True, "message": "连接成功", "latency_ms": round(latency, 1)}
        return {"provider": body.provider, "success": False, "message": "Connected but returned empty data", "latency_ms": round(latency, 1)}
    except Exception as exc:
        latency = (time.time() - start) * 1000
        return {"provider": body.provider, "success": False, "message": str(exc)[:200], "latency_ms": round(latency, 1)}


@public_router.post("/auth/llm-login")
async def llm_login(body: schemas.LLMQuickLoginRequest):
    from app.api.auth import _hash_token, generate_tokens
    from app.config import get_settings
    from app.harness.llm_config import get_llm_config_store

    probe = await _run_llm_probe(body)
    if not probe.get("success"):
        return probe

    settings = get_settings()
    token = ""
    # Derive a stable user_id from the LLM api_key so the same user
    # always gets the same identity across restarts and re-logins.
    user_id = f"llm-{_hash_token(body.api_key)}"
    if settings.api_token:
        token = generate_tokens(1, user_id=user_id)[0]
    else:
        user_id = "default-user"

    store = get_llm_config_store()
    store.upsert_config(
        user_id,
        provider=body.provider,
        api_key=body.api_key,
        base_url=body.base_url,
        tool_calling_model=body.tool_calling_model,
        reasoning_model=body.reasoning_model,
        tool_calling_temperature=body.tool_calling_temperature,
        reasoning_temperature=body.reasoning_temperature,
        max_tokens=body.max_tokens,
        enabled=True,
    )
    return {"status": "ok", "token": token, "user_id": user_id, "provider": body.provider, "latency_ms": probe.get("latency_ms")}


@router.post("/auth/tokens")
async def create_tokens(count: int = 5):
    """Generate one-time tokens (admin only — use master key).

    Usage: ``POST /api/v1/auth/tokens?count=10``
    with header ``Authorization: Bearer <master_key>``
    """
    from app.api.auth import generate_tokens
    tokens = generate_tokens(count)
    return {"tokens": tokens, "count": len(tokens)}


@router.get("/auth/tokens")
async def list_tokens():
    """View current token pool status (admin only)."""
    from app.api.auth import get_pool_status
    return get_pool_status()


_logout_bearer = HTTPBearer(auto_error=False)


@router.post("/auth/logout")
async def auth_logout(
    credentials: HTTPAuthorizationCredentials | None = Security(_logout_bearer),
):
    """Consume the caller's one-time token on logout."""
    from app.api.auth import consume_token
    token = credentials.credentials if credentials else ""
    consumed = consume_token(token)
    return {"status": "consumed" if consumed else "ok"}


# ---------------------------------------------------------------------------
# Chat (free-form)
# ---------------------------------------------------------------------------

_NODE_TOOL_MAP: dict[str, list[str]] = {
    "strong_stocks": ["get_strong_stocks"],
    "gather_data": ["get_financial_statements", "get_key_metrics", "get_company_profile",
                     "get_peer_comparison", "get_risk_metrics", "get_catalysts"],
    "sentiment": ["get_company_news", "web_search", "get_policy_events"],
    "update_config": [],
    "watchlist_add": [],
}

# Nodes whose on_chain_end output may carry side-effect payloads for the frontend
_SIDE_EFFECT_NODES = frozenset({"update_config", "watchlist_add", "strong_stocks"})


# Nodes whose LLM tokens should be streamed to the user.
# Internal classifiers (parse_input, resolve_symbol) must NOT leak tokens.
_TOKEN_VISIBLE_NODES = frozenset({
    "chat", "synthesis", "gather_data", "sentiment", "render_output",
})


class _ThinkFilter:
    """Stateful filter that strips <think>…</think> blocks from a token stream.

    Tokens arrive as small chunks; open/close tags may be split across chunks.
    We buffer potential tag fragments and only emit content outside think blocks.
    """
    def __init__(self) -> None:
        self._inside = False
        self._buf = ""

    def feed(self, text: str) -> str:
        """Feed a chunk and return the filtered (visible) portion."""
        self._buf += text
        out: list[str] = []
        while self._buf:
            if self._inside:
                end = self._buf.find("</think>")
                if end == -1:
                    # might be a partial closing tag at the tail
                    if self._buf.endswith(tuple("</think>"[:i] for i in range(1, 8))):
                        break  # wait for more data
                    self._buf = ""
                    break
                self._buf = self._buf[end + 8:]  # skip past </think>
                self._inside = False
            else:
                start = self._buf.find("<think>")
                if start == -1:
                    # check for partial opening tag at tail
                    for i in range(1, 7):
                        if self._buf.endswith("<think>"[:i]):
                            out.append(self._buf[:-i])
                            self._buf = self._buf[-i:]
                            break
                    else:
                        out.append(self._buf)
                        self._buf = ""
                    break
                out.append(self._buf[:start])
                self._buf = self._buf[start + 7:]  # skip past <think>
                self._inside = True
        return "".join(out)

    def flush(self) -> str:
        """Return any remaining buffered content (outside a think block)."""
        if self._inside:
            return ""
        result = self._buf
        self._buf = ""
        return result


def _strip_think_tags(text: str) -> str:
    """Remove all <think>…</think> blocks from a complete string."""
    import re
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


async def _stream_events(graph, input_state: dict, config: dict, *, skip_ticker_select: bool = False) -> AsyncGenerator[str, None]:
    """Yield SSE events from LangGraph's astream_events."""
    token_sent = False
    think_filter = _ThinkFilter()
    _pending_ticker: str | None = None  # ticker awaiting name from resolve_symbol
    async for event in graph.astream_events(input_state, config=config, version="v2"):
        kind = event.get("event", "")
        if kind == "on_chat_model_stream":
            # Filter: only stream tokens from user-facing nodes
            node = (event.get("metadata") or {}).get("langgraph_node", "")
            if node and node not in _TOKEN_VISIBLE_NODES:
                continue
            # Skip internal LLM calls (e.g. Phase 1 intent detection in chat_node)
            tags = event.get("tags") or []
            if "internal" in tags:
                continue
            chunk = event.get("data", {}).get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                visible = think_filter.feed(chunk.content)
                if visible:
                    payload = json.dumps({"type": "token", "content": visible}, ensure_ascii=False)
                    yield f"data: {payload}\n\n"
                    token_sent = True
        elif kind == "on_tool_start":
            name = event.get("name", "")
            payload = json.dumps({"type": "tool_start", "tool": name}, ensure_ascii=False)
            yield f"data: {payload}\n\n"
        elif kind == "on_tool_end":
            name = event.get("name", "")
            payload = json.dumps({"type": "tool_end", "tool": name}, ensure_ascii=False)
            yield f"data: {payload}\n\n"
        elif kind == "on_chain_start":
            name = event.get("name", "")
            # Flush pending ticker_select if a downstream node starts without resolve providing a name
            if _pending_ticker and not skip_ticker_select and name in _NODE_TOOL_MAP:
                evt_flush: dict[str, str] = {"type": "ticker_select", "ticker": _pending_ticker}
                yield f"data: {json.dumps(evt_flush, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return
            if name in _NODE_TOOL_MAP:
                payload = json.dumps({"type": "step_start", "node": name,
                                      "tools": _NODE_TOOL_MAP[name]}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
        elif kind == "on_custom_event":
            # Custom events emitted by nodes (e.g. ticker_select, harness_event)
            cname = event.get("name", "")
            if cname == "harness_event":
                cdata = event.get("data", {})
                # tool_call events are internal journal entries, not user-facing
                if cdata.get("module") == "tool_call":
                    continue
                payload = json.dumps({"type": "harness_event", **cdata}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
            elif cname == "ticker_select" and not skip_ticker_select:
                cdata = event.get("data", {})
                ticker = cdata.get("ticker", "")
                name = cdata.get("name", "")
                if ticker:
                    if not name and _pending_ticker is None:
                        # First ticker_select from parse_input (no name yet).
                        # Hold it — resolve_symbol_node will re-emit with name.
                        _pending_ticker = ticker
                        continue
                    # Either this event has a name (from resolve_symbol), or it's
                    # a second event for an already-pending ticker (fallback).
                    final_ticker = ticker or _pending_ticker or ""
                    logger.info("SSE: ticker_select — ticker=%s name=%s", final_ticker, name)
                    evt: dict[str, str] = {"type": "ticker_select", "ticker": final_ticker}
                    if name:
                        evt["name"] = name
                    payload = json.dumps(evt, ensure_ascii=False)
                    yield f"data: {payload}\n\n"
                    # Stream closed — analysis delegated to /analyze, chat unlocked
                    yield "data: [DONE]\n\n"
                    return
            elif cname == "resolve_fail":
                cdata = event.get("data", {})
                msg = cdata.get("message", "")
                query = cdata.get("query", "")
                logger.info("SSE: resolve_fail — query=%s", query)
                _pending_ticker = None  # discard pending ticker_select
                payload = json.dumps(
                    {"type": "resolve_fail", "query": query, "message": msg},
                    ensure_ascii=False,
                )
                yield f"data: {payload}\n\n"
                yield "data: [DONE]\n\n"
                return
            elif cname == "intent_done":
                # Multi-intent queue: immediately flush each completed intent's result
                cdata = event.get("data", {})
                content = cdata.get("content", "")
                intent_name = cdata.get("intent", "")
                q_idx = cdata.get("index", 0)
                q_total = cdata.get("total", 1)
                if content:
                    logger.info(
                        "SSE: intent_done [%d/%d] intent=%s chars=%d",
                        q_idx + 1, q_total, intent_name, len(content),
                    )
                    clean = _strip_think_tags(content)
                    if clean:
                        payload = json.dumps(
                            {"type": "intent_done", "intent": intent_name,
                             "index": q_idx, "total": q_total, "content": clean},
                            ensure_ascii=False,
                        )
                        yield f"data: {payload}\n\n"
                        token_sent = True
            elif cname == "watchlist_update":
                cdata = event.get("data", {})
                wl_tickers = cdata.get("tickers", [])
                wl_action = cdata.get("action", "add")
                if wl_tickers:
                    logger.info("SSE: watchlist_update — action=%s tickers=%s", wl_action, wl_tickers)
                    payload = json.dumps(
                        {"type": "watchlist_update", "tickers": wl_tickers, "action": wl_action},
                        ensure_ascii=False,
                    )
                    yield f"data: {payload}\n\n"
            elif cname == "multi_analyze":
                cdata = event.get("data", {})
                tickers_list = cdata.get("tickers", [])
                if tickers_list:
                    logger.info("SSE: multi_analyze — tickers=%s", tickers_list)
                    payload = json.dumps(
                        {"type": "multi_analyze", "tickers": tickers_list},
                        ensure_ascii=False,
                    )
                    yield f"data: {payload}\n\n"
        elif kind == "on_chain_end":
            name = event.get("name", "")
            lg_node = (event.get("metadata") or {}).get("langgraph_node", "")
            if name in _NODE_TOOL_MAP:
                payload = json.dumps({"type": "step_end", "node": name}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
            if name in _SIDE_EFFECT_NODES or lg_node in _SIDE_EFFECT_NODES:
                output = event.get("data", {}).get("output") or {}
                logger.info("SSE: on_chain_end name=%s lg_node=%s output_keys=%s", name, lg_node, list(output.keys()) if output else [])
                if "config_update" in output and output["config_update"]:
                    payload = json.dumps(
                        {"type": "config_update", "params": output["config_update"]},
                        ensure_ascii=False,
                    )
                    yield f"data: {payload}\n\n"
                if "watchlist_update" in output and output["watchlist_update"]:
                    payload = json.dumps(
                        {"type": "watchlist_update", "tickers": output["watchlist_update"]},
                        ensure_ascii=False,
                    )
                    yield f"data: {payload}\n\n"

    # Check if graph is paused at interrupt (ambiguous tickers)
    try:
        thread_id = config.get("configurable", {}).get("thread_id")
        if thread_id:
            state = await graph.aget_state(make_thread_config(thread_id))
            ambiguous = state.values.get("ambiguous_tickers") or []
            if ambiguous:
                logger.info("SSE: graph interrupted — ambiguous tickers: %s", ambiguous)
                payload = json.dumps(
                    {"type": "disambiguate", "tickers": ambiguous, "session_id": thread_id},
                    ensure_ascii=False,
                )
                yield f"data: {payload}\n\n"
                yield "data: [DONE]\n\n"
                return
    except Exception as exc:
        logger.debug("Interrupt check failed: %s", exc)

    # Flows without LLM calls (e.g. strong_stocks, update_config) never emit
    # on_chat_model_stream events.  Flush the final AIMessage as a single token
    # so the frontend receives the result instead of a blank bubble.
    if not token_sent:
        try:
            thread_id = config.get("configurable", {}).get("thread_id")
            if thread_id:
                state = await graph.aget_state(make_thread_config(thread_id))
                for m in reversed(state.values.get("messages", [])):
                    if isinstance(m, AIMessage) and m.content:
                        clean = _strip_think_tags(m.content)
                        if clean:
                            payload = json.dumps(
                                {"type": "token", "content": clean},
                                ensure_ascii=False,
                            )
                            yield f"data: {payload}\n\n"
                        break
        except Exception:
            pass

    yield "data: [DONE]\n\n"


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user_id: str = Depends(get_current_user_id)):
    _current_user_id_var.set(user_id)
    graph = get_compiled_graph()
    config = make_thread_config(req.session_id)
    session_id = config["configurable"]["thread_id"]
    callbacks, tracker, journal = get_fresh_callbacks(
        session_id=session_id, user_id=user_id,
        run_tags=["chat"],
        run_metadata={"intent": "chat"},
    )
    asyncio.create_task(_upsert_user(user_id))

    input_state = {
        "messages": [HumanMessage(content=req.message)],
        "session_id": session_id,
        "user_id": user_id,
    }
    run_config = {
        **config,
        "callbacks": callbacks,
        "tags": ["chat", f"user:{user_id}"],
        "metadata": {"session_id": session_id, "user_id": user_id, "intent": "chat"},
    }

    if req.stream:
        async def _chat_stream():
            async for line in _stream_events(graph, input_state, run_config):
                yield line
            asyncio.create_task(_flush_journal_and_summarize(journal))

        return StreamingResponse(
            _chat_stream(),
            media_type="text/event-stream",
            headers={"X-Session-Id": session_id},
        )

    result = await graph.ainvoke(input_state, config=run_config)
    asyncio.create_task(_flush_journal_and_summarize(journal))
    final_msg = ""
    for m in reversed(result.get("messages", [])):
        if isinstance(m, AIMessage) and m.content:
            final_msg = m.content
            break

    return ChatResponse(
        session_id=session_id,
        message=final_msg,
        usage=tracker.stats,
        config_update=result.get("config_update") or None,
        watchlist_update=result.get("watchlist_update") or None,
    )


# ---------------------------------------------------------------------------
# Chat resume (Human-in-the-loop disambiguation)
# ---------------------------------------------------------------------------


class _ResumeRequest(BaseModel):
    session_id: str = PydanticField(description="Session to resume")
    selected_ticker: str = PydanticField(description="Ticker chosen by the user")
    stream: bool = PydanticField(default=True)


@router.post("/chat/resume")
async def resume_chat(req: _ResumeRequest):
    """Resume graph after human_confirm interrupt with the user's ticker choice."""
    from app.memory.store import make_thread_config as _mtc

    graph = get_compiled_graph()
    config = _mtc(req.session_id)
    ticker = req.selected_ticker.strip().upper()

    # Provide the user's selection by writing state *as* the human_confirm node
    await graph.aupdate_state(
        config,
        {
            "ambiguous_tickers": [],
            "resolved_symbol": ticker,
            "tickers": [ticker],
        },
        as_node="human_confirm",
    )

    if req.stream:
        callbacks, tracker, journal = get_fresh_callbacks(
            session_id=req.session_id,
            run_tags=["resume", f"ticker:{ticker}"],
            run_metadata={"intent": "resume", "ticker": ticker},
        )
        run_config = {
            **config,
            "callbacks": callbacks,
            "tags": ["resume", f"ticker:{ticker}"],
            "metadata": {"session_id": req.session_id, "intent": "resume", "ticker": ticker},
        }

        async def _resume_stream():
            async for sse_line in _stream_events(graph, None, run_config):
                yield sse_line
            asyncio.create_task(_flush_journal_and_summarize(journal))

        return StreamingResponse(
            _resume_stream(),
            media_type="text/event-stream",
            headers={"X-Session-Id": req.session_id},
        )

    # Non-streaming fallback
    result = await graph.ainvoke(None, config=config)
    final_msg = ""
    for m in reversed(result.get("messages", [])):
        if isinstance(m, AIMessage) and m.content:
            final_msg = m.content
            break
    return {"session_id": req.session_id, "message": final_msg}


# ---------------------------------------------------------------------------
# Fundamental deep documents (RAG ingest)
# ---------------------------------------------------------------------------


@router.post("/fundamental-documents", response_model=FundamentalDocumentIngestResponse)
async def ingest_fundamental_documents(req: FundamentalDocumentIngestRequest):
    """Index filing / MD&A text for the session; use before analyze or chat on the same thread."""
    await asyncio.to_thread(
        ingest_fundamental_deep_documents,
        req.text,
        session_id=req.session_id.strip(),
        ticker=req.ticker.strip(),
        doc_label=req.doc_label or "",
    )
    return FundamentalDocumentIngestResponse(
        session_id=req.session_id.strip(),
        ticker=req.ticker.strip(),
        ingested=True,
    )


# ---------------------------------------------------------------------------
# Analyze (single stock)
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest, user_id: str = Depends(get_current_user_id)):
    _current_user_id_var.set(user_id)
    graph = get_compiled_graph()
    config = make_thread_config(req.session_id)
    session_id = config["configurable"]["thread_id"]
    callbacks, tracker, journal = get_fresh_callbacks(
        session_id=session_id, user_id=user_id,
        run_tags=["analyze", f"ticker:{req.ticker}"],
        run_metadata={"intent": "analyze", "ticker": req.ticker},
    )
    asyncio.create_task(_track_analysis(user_id))

    if req.deep_document_text and req.deep_document_text.strip():
        await asyncio.to_thread(
            ingest_fundamental_deep_documents,
            req.deep_document_text.strip(),
            session_id=session_id,
            ticker=req.ticker.strip(),
            doc_label="analyze_request",
        )

    query = f"Please provide a comprehensive fundamental analysis for {req.ticker}"
    input_state = {
        "messages": [HumanMessage(content=query)],
        "session_id": session_id,
        "user_id": user_id,
    }
    run_config = {
        **config,
        "callbacks": callbacks,
        "tags": ["analyze", f"ticker:{req.ticker}", f"user:{user_id}"],
        "metadata": {"session_id": session_id, "user_id": user_id, "intent": "analyze", "ticker": req.ticker},
    }

    def _extract_result(result: dict, ticker: str, sid: str, usage: dict) -> dict:
        """Extract AnalyzeResponse-compatible dict from graph result."""
        report = result.get("markdown_report", "")
        if not report:
            for m in reversed(result.get("messages", [])):
                if isinstance(m, AIMessage) and m.content:
                    report = m.content
                    break
        raw_errors = result.get("errors") or []
        errors_clean = [str(e) for e in raw_errors if e is not None]
        structured = result.get("structured_report")
        if structured is not None:
            try:
                structured = json.loads(json.dumps(structured, default=str))
            except Exception:
                structured = None
        evidence_chain = result.get("evidence_chain") or []
        retrieval_debug = result.get("retrieval_debug") or {}
        try:
            evidence_chain = json.loads(json.dumps(evidence_chain, default=str))
        except Exception:
            evidence_chain = []
        try:
            retrieval_debug = json.loads(json.dumps(retrieval_debug, default=str))
        except Exception:
            retrieval_debug = {}
        return {
            "ticker": ticker,
            "session_id": sid,
            "report": report or "",
            "structured": structured,
            "errors": errors_clean,
            "evidence_chain": evidence_chain,
            "retrieval_debug": retrieval_debug,
            "usage": usage,
        }

    if req.stream:
        async def _stream_analyze():
            """Stream progress events, then emit final result before [DONE]."""
            async for sse_line in _stream_events(graph, input_state, run_config, skip_ticker_select=True):
                if sse_line == "data: [DONE]\n\n":
                    # Before closing, fetch state and emit structured result
                    try:
                        state = await graph.aget_state(make_thread_config(session_id))
                        result_data = _extract_result(
                            state.values, req.ticker, session_id, tracker.stats
                        )
                        payload = json.dumps(
                            {"type": "result", **result_data}, ensure_ascii=False, default=str
                        )
                        yield f"data: {payload}\n\n"
                    except Exception as exc:
                        logger.warning("Failed to extract result for stream: %s", exc)
                    yield "data: [DONE]\n\n"
                    return
                yield sse_line
            # If _stream_events ended without [DONE], still emit result
            try:
                state = await graph.aget_state(make_thread_config(session_id))
                result_data = _extract_result(
                    state.values, req.ticker, session_id, tracker.stats
                )
                payload = json.dumps(
                    {"type": "result", **result_data}, ensure_ascii=False, default=str
                )
                yield f"data: {payload}\n\n"
            except Exception as exc:
                logger.warning("Failed to extract result for stream (fallback): %s", exc)
            yield "data: [DONE]\n\n"
            asyncio.create_task(_flush_journal_and_summarize(journal))

        return StreamingResponse(
            _stream_analyze(),
            media_type="text/event-stream",
            headers={"X-Session-Id": session_id},
        )

    try:
        result = await graph.ainvoke(input_state, config=run_config)
    except Exception as exc:
        logger.error("graph.ainvoke failed for %s: %s", req.ticker, exc, exc_info=True)
        raise
    finally:
        asyncio.create_task(_flush_journal_and_summarize(journal))

    return AnalyzeResponse(
        **_extract_result(result, req.ticker, session_id, tracker.stats)
    )


# ---------------------------------------------------------------------------
# Strong stocks
# ---------------------------------------------------------------------------

@router.post("/strong-stocks", response_model=StrongStocksResponse)
async def strong_stocks(req: StrongStocksRequest):
    data = await asyncio.to_thread(
        load_strong_stocks_with_params,
        req.market_type,
        req.top_count,
        req.rsi_threshold,
        req.momentum_days,
        req.top_volume_count,
        req.sort_by,
        req.min_volume_turnover,
    )
    return StrongStocksResponse(
        market_type=req.market_type,
        stocks=data.get("stocks", []),
        filters_applied=data.get("filters_applied", {}),
    )


@router.post("/strong-stocks/single", response_model=SingleStrongStockResponse)
async def single_strong_stock(req: SingleStrongStockRequest):
    try:
        stock = await asyncio.to_thread(load_single_strong_stock, req.ticker, req.market_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("single_strong_stock failed for %s (%s): %s", req.ticker, req.market_type, exc)
        raise HTTPException(status_code=502, detail=f"Failed to load recent metrics for {req.ticker}") from exc
    return SingleStrongStockResponse(
        market_type=req.market_type,
        stock=stock,
    )


# ---------------------------------------------------------------------------
# Session history
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Retrieve conversation history for a session."""
    graph = get_compiled_graph()
    config = make_thread_config(session_id)
    try:
        state = await graph.aget_state(config)
        messages = []
        for m in state.values.get("messages", []):
            messages.append({
                "role": "user" if isinstance(m, HumanMessage) else "assistant",
                "content": m.content,
            })
        return {"session_id": session_id, "messages": messages}
    except Exception:
        return {"session_id": session_id, "messages": []}


# ---------------------------------------------------------------------------
# Watchlist CRUD
# ---------------------------------------------------------------------------

@router.get("/watchlist/{user_id}", response_model=WatchlistResponse)
async def get_watchlist(user_id: str):
    """List all tickers in a user's watchlist."""
    from app.memory.watchlist import list_tickers

    items = await list_tickers(user_id)
    return WatchlistResponse(user_id=user_id, watchlist=items, count=len(items))


@router.post("/watchlist", response_model=WatchlistResponse)
async def add_to_watchlist(req: WatchlistAddRequest, request: Request):
    """Add a ticker to the user's watchlist (upsert)."""
    from app.memory.watchlist import add_ticker, list_tickers

    await add_ticker(req.user_id, req.ticker, req.note)
    try:
        await _get_resident_agent_service(request).sync_watchlist(req.user_id)
    except Exception as exc:
        logger.warning("Resident agent watchlist sync failed after add: %s", exc)
    items = await list_tickers(req.user_id)
    return WatchlistResponse(user_id=req.user_id, watchlist=items, count=len(items))


@router.put("/watchlist", response_model=WatchlistResponse)
async def update_watchlist_note(req: WatchlistUpdateRequest):
    """Update the note for an existing watchlist entry."""
    from app.memory.watchlist import update_note, list_tickers

    found = await update_note(req.user_id, req.ticker, req.note)
    if not found:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"{req.ticker} not in watchlist")
    items = await list_tickers(req.user_id)
    return WatchlistResponse(user_id=req.user_id, watchlist=items, count=len(items))


@router.delete("/watchlist/{user_id}/{ticker}")
async def remove_from_watchlist(user_id: str, ticker: str, request: Request):
    """Remove a single ticker from the watchlist."""
    from app.memory.watchlist import remove_ticker

    deleted = await remove_ticker(user_id, ticker)
    if not deleted:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"{ticker} not in watchlist")
    try:
        await _get_resident_agent_service(request).sync_watchlist(user_id)
    except Exception as exc:
        logger.warning("Resident agent watchlist sync failed after remove: %s", exc)
    return {"ok": True, "removed": ticker.upper()}


@router.delete("/watchlist/{user_id}")
async def clear_watchlist(user_id: str, request: Request):
    """Remove all tickers from the watchlist."""
    from app.memory.watchlist import clear_all

    count = await clear_all(user_id)
    try:
        await _get_resident_agent_service(request).sync_watchlist(user_id)
    except Exception as exc:
        logger.warning("Resident agent watchlist sync failed after clear: %s", exc)
    return {"ok": True, "removed_count": count}


# ---------------------------------------------------------------------------
# Resident Agent — watchlist-driven autonomous mode
# ---------------------------------------------------------------------------

@router.get("/resident-agent/{user_id}", response_model=schemas.ResidentAgentStatusResponse)
async def get_resident_agent_status(user_id: str, request: Request):
    service = _get_resident_agent_service(request)
    data = await service.get_status(user_id)
    return schemas.ResidentAgentStatusResponse.model_validate(data)


@router.put("/resident-agent/{user_id}", response_model=schemas.ResidentAgentStatusResponse)
async def update_resident_agent_status(
    user_id: str,
    req: schemas.ResidentAgentUpdateRequest,
    request: Request,
):
    service = _get_resident_agent_service(request)
    if req.enabled is False:
        data = await service.stop_user(user_id)
    elif req.enabled is True:
        data = await service.start_user(
            user_id,
            interval_seconds=req.interval_seconds,
            run_immediately=req.run_immediately,
        )
    elif req.interval_seconds is not None:
        data = await service.update_settings(
            user_id,
            interval_seconds=req.interval_seconds,
        )
    else:
        data = await service.sync_watchlist(user_id)
    return schemas.ResidentAgentStatusResponse.model_validate(data)


@router.post("/resident-agent/{user_id}/run", response_model=schemas.ResidentAgentStatusResponse)
async def run_resident_agent_once(user_id: str, request: Request):
    service = _get_resident_agent_service(request)
    data = await service.run_once(user_id)
    return schemas.ResidentAgentStatusResponse.model_validate(data)


# ---------------------------------------------------------------------------
# Long-term Memory CRUD
# ---------------------------------------------------------------------------


@router.get("/memory/{user_id}")
async def list_memories(user_id: str):
    """List all memories for a user, grouped by category."""
    from app.harness.long_term_memory import LongTermMemory

    ltm = await LongTermMemory.create()
    entries = await ltm.recall(user_id, top_k=50)
    await ltm.close()

    grouped: dict[str, list[dict]] = {}
    for e in entries:
        grouped.setdefault(e.category, []).append({
            "key": e.key,
            "content": e.content,
            "updated_at": e.updated_at,
            "access_count": e.access_count,
        })
    return {"user_id": user_id, "memories": grouped, "total": len(entries)}


@router.get("/memory/{user_id}/{category}")
async def list_memories_by_category(user_id: str, category: str):
    """List memories for a user filtered by category."""
    from app.harness.long_term_memory import LongTermMemory

    ltm = await LongTermMemory.create()
    entries = await ltm.recall(user_id, category=category, top_k=50)
    await ltm.close()

    items = [{
        "key": e.key,
        "content": e.content,
        "updated_at": e.updated_at,
        "access_count": e.access_count,
    } for e in entries]
    return {"user_id": user_id, "category": category, "memories": items, "total": len(items)}


@router.delete("/memory/{user_id}/{category}/{key}")
async def delete_memory(user_id: str, category: str, key: str):
    """Delete a single memory entry."""
    from app.harness.long_term_memory import LongTermMemory

    ltm = await LongTermMemory.create()
    deleted = await ltm.forget(user_id, category, key)
    await ltm.close()

    if not deleted:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Memory not found: {category}/{key}")
    return {"ok": True, "deleted": f"{category}/{key}"}


@router.delete("/memory/{user_id}")
async def clear_all_memories(user_id: str):
    """Clear all memories for a user."""
    from app.harness.long_term_memory import LongTermMemory

    ltm = await LongTermMemory.create()
    cursor = await ltm._conn.execute(
        "DELETE FROM user_memory WHERE user_id = ?", (user_id,)
    )
    await ltm._conn.commit()
    count = cursor.rowcount
    await ltm.close()
    return {"ok": True, "removed_count": count}


# ---------------------------------------------------------------------------
# Watchlist upcoming events (real calendar data)
# ---------------------------------------------------------------------------


class _WatchlistEventsRequest(BaseModel):
    tickers: list[str] = PydanticField(description="List of tickers to fetch events for")
    lookback_days: int = PydanticField(default=30, description="Include events this many days in the past")


@router.post("/watchlist-events")
async def watchlist_events(req: _WatchlistEventsRequest):
    """Return upcoming calendar events (earnings, dividends, policy) for the given tickers."""
    from app.providers.ticker_cache import get_yf_calendar
    from app.providers.policy_events import get_upcoming_policy_events
    from datetime import date, datetime
    import re

    events: list[dict] = []
    today = date.today()
    lookback_start = today - timedelta(days=req.lookback_days)

    def _parse_earnings_date(raw: str) -> date | None:
        """Parse earnings date from yfinance calendar (may be repr of list)."""
        if not raw:
            return None
        # "[datetime.date(2026, 4, 23)]" → extract numbers
        m = re.search(r"(\d{4}),\s*(\d{1,2}),\s*(\d{1,2})", str(raw))
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        # "2026-04-23" format
        try:
            return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
        except Exception:
            return None

    def _fetch_one(ticker: str) -> list[dict]:
        ticker_events = []
        try:
            cal = get_yf_calendar(ticker)
            if not cal or not isinstance(cal, dict):
                return []
            # Earnings date
            ed = _parse_earnings_date(cal.get("Earnings Date", ""))
            if ed and ed >= lookback_start:
                days = (ed - today).days
                ticker_events.append({
                    "ticker": ticker.upper(),
                    "event": "财报发布",
                    "date": ed.isoformat(),
                    "days_away": days,
                    "detail": f"EPS预期 {cal.get('Earnings Average', 'N/A')}",
                    "category": "earnings",
                })
            # Dividend date
            for key, label in [("Dividend Date", "派息日"), ("Ex-Dividend Date", "除息日")]:
                raw = cal.get(key)
                if raw:
                    try:
                        d = datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
                        if d >= lookback_start:
                            ticker_events.append({
                                "ticker": ticker.upper(),
                                "event": label,
                                "date": d.isoformat(),
                                "days_away": (d - today).days,
                                "category": "dividend",
                            })
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug("Calendar fetch failed for %s: %s", ticker, exc)
        return ticker_events

    # Fetch ticker events in parallel threads
    tasks = [asyncio.to_thread(_fetch_one, t) for t in req.tickers[:30]]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, list):
            events.extend(r)

    # Append macro / policy events (includes recent past)
    try:
        events.extend(get_upcoming_policy_events(lookback_days=req.lookback_days))
    except Exception as exc:
        logger.debug("Policy events fetch failed: %s", exc)

    # Sort by date ascending
    events.sort(key=lambda e: e.get("date", "9999"))
    return {"events": events}


# ---------------------------------------------------------------------------
# Admin — Market cache refresh
# ---------------------------------------------------------------------------

@router.post("/admin/refresh-market-cache")
async def refresh_market_cache():
    """Manually trigger a full market-cache refresh (index snapshots + strong stocks).

    The refresh writes to SQLite so all subsequent tool reads hit the cache
    instead of calling yfinance directly.
    """
    from app.providers.market_cache import refresh_all

    try:
        result = await refresh_all()
        return {"ok": True, "result": result}
    except Exception as exc:
        logger.error("Market cache refresh failed: %s", exc, exc_info=True)
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Harness — Run Journal & Metrics
# ---------------------------------------------------------------------------

@router.get("/harness/runs/{session_id}/journal")
async def get_run_journal(session_id: str):
    """Return the full decision journal for a session's runs."""
    import aiosqlite
    from app.config import get_settings

    settings = get_settings()
    db_path = settings.harness_journal_db_path or settings.checkpoint_db_path
    try:
        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute(
                "SELECT run_id, entry_idx, entry_json, created_at "
                "FROM run_journal WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            )
            rows = await cursor.fetchall()
            import json as _json
            entries = [
                {"run_id": r[0], "entry_idx": r[1],
                 "entry": _json.loads(r[2]), "created_at": r[3]}
                for r in rows
            ]
            return {"session_id": session_id, "entries": entries, "count": len(entries)}
    except Exception as exc:
        return {"session_id": session_id, "entries": [], "error": str(exc)}


@router.get("/harness/runs/{session_id}/metrics")
async def get_run_metrics(session_id: str):
    """Return aggregated metrics for a session's runs."""
    import aiosqlite
    import json as _json
    from app.config import get_settings

    settings = get_settings()
    db_path = settings.harness_journal_db_path or settings.checkpoint_db_path
    try:
        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute(
                "SELECT entry_json FROM run_journal WHERE session_id = ?",
                (session_id,),
            )
            rows = await cursor.fetchall()
            total_tokens = 0
            tool_calls = 0
            errors = 0
            recoveries = 0
            for r in rows:
                data = _json.loads(r[0])
                event_type = data.get("event_type", "")
                if event_type == "tool_call":
                    tool_calls += 1
                elif event_type == "error":
                    errors += 1
                elif event_type == "recovery":
                    recoveries += 1
                usage = data.get("token_usage", {})
                total_tokens += sum(usage.values()) if usage else 0
            return {
                "session_id": session_id,
                "total_entries": len(rows),
                "tool_calls": tool_calls,
                "errors": errors,
                "recoveries": recoveries,
                "total_tokens": total_tokens,
            }
    except Exception as exc:
        return {"session_id": session_id, "error": str(exc)}


@router.get("/harness/dashboard")
async def harness_dashboard():
    """Return aggregated harness metrics (resume-ready indicators)."""
    from app.harness.metrics import MetricsAggregator

    try:
        agg = await MetricsAggregator.create()
        data = await agg.dashboard()
        await agg.close()
        return data
    except Exception as exc:
        logger.error("Harness dashboard failed: %s", exc, exc_info=True)
        return {"error": str(exc)}


@router.get("/harness/breakers")
async def harness_breakers():
    """Return circuit breaker status for all registered external services."""
    from app.harness.circuit_breaker import all_breakers
    return {"breakers": all_breakers()}


@router.get("/harness/pool-refresh")
async def harness_pool_refresh_status(request: Request):
    """Return APScheduler daily pool-refresh status and next run times."""
    pool_refresh = getattr(request.app.state, "pool_refresh", None)
    if pool_refresh is None:
        return {"enabled": False, "jobs": []}
    return {
        "enabled": True,
        "jobs": pool_refresh.list_jobs(),
    }


@router.post("/harness/pool-refresh/{market_type}")
async def harness_pool_refresh_trigger(market_type: str, request: Request):
    """Manually trigger a monitor-pool rebuild for the given market type."""
    if market_type not in {"us_stock", "etf", "hk_stock"}:
        raise HTTPException(status_code=400, detail=f"Unknown market_type: {market_type}")
    pool_refresh = getattr(request.app.state, "pool_refresh", None)
    if pool_refresh is None:
        raise HTTPException(status_code=503, detail="Pool refresh scheduler unavailable")
    return await pool_refresh.trigger_now(market_type)


@router.get("/harness/users")
async def harness_users(limit: int = 100):
    """Return all tracked users (admin/metrics)."""
    from app.harness.user_store import UserStore
    try:
        store = await UserStore.create()
        users = await store.list_all(limit=limit)
        await store.close()
        return {"users": users, "count": len(users)}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Task Lifecycle — autonomous task CRUD + cycle execution
# ---------------------------------------------------------------------------

@router.post("/tasks", response_model=TaskResponse)
async def create_task(req: TaskCreateRequest):
    """Create a new autonomous analysis task."""
    from app.harness.task_spec import TaskSpecStore

    store = await TaskSpecStore.create()
    spec = await store.create_task(
        user_id=req.user_id,
        goal=req.goal,
        ticker_scope=req.ticker_scope,
        cadence=req.cadence,
        report_template=req.report_template,
        kpi_constraints=req.kpi_constraints,
        stop_conditions=req.stop_conditions,
        escalation_policy=req.escalation_policy,
    )
    await store.close()
    return TaskResponse(**spec.to_dict())


@router.get("/tasks/{user_id}", response_model=TaskListResponse)
async def list_tasks(user_id: str, status: str | None = None):
    """List all tasks for a user."""
    from app.harness.task_spec import TaskSpecStore

    store = await TaskSpecStore.create()
    tasks = await store.list_tasks(user_id, status=status)
    await store.close()
    return TaskListResponse(
        user_id=user_id,
        tasks=[TaskResponse(**t.to_dict()) for t in tasks],
        count=len(tasks),
    )


@router.get("/tasks/{user_id}/{task_id}", response_model=TaskResponse)
async def get_task(user_id: str, task_id: str):
    """Get a single task's details."""
    from app.harness.task_spec import TaskSpecStore
    from fastapi import HTTPException

    store = await TaskSpecStore.create()
    spec = await store.get_task(user_id, task_id)
    await store.close()
    if not spec:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return TaskResponse(**spec.to_dict())


@router.patch("/tasks/{user_id}/{task_id}", response_model=TaskResponse)
async def update_task(user_id: str, task_id: str, req: TaskUpdateRequest):
    """Update a task's mutable fields."""
    from app.harness.task_spec import TaskSpecStore
    from fastapi import HTTPException

    store = await TaskSpecStore.create()
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    spec = await store.update_task(user_id, task_id, **fields)
    await store.close()
    if not spec:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return TaskResponse(**spec.to_dict())


@router.delete("/tasks/{user_id}/{task_id}")
async def delete_task(user_id: str, task_id: str):
    """Delete a task."""
    from app.harness.task_spec import TaskSpecStore
    from fastapi import HTTPException

    store = await TaskSpecStore.create()
    deleted = await store.delete_task(user_id, task_id)
    await store.close()
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return {"ok": True, "deleted": task_id}


@router.post("/tasks/{user_id}/{task_id}/run")
async def run_task_cycle(user_id: str, task_id: str):
    """Manually trigger a single autonomous cycle for a task.

    Streams SSE progress events during execution, then sends the final result.
    Falls back to plain JSON if the client doesn't accept SSE.
    """
    from app.harness.scheduler import TaskScheduler
    from app.config import get_settings

    settings = get_settings()
    scheduler = TaskScheduler(cycle_timeout=settings.cycle_timeout_seconds)

    _STEP_LABELS: dict[str, str] = {
        "parse_input": "解析意图",
        "resolve_symbol": "解析标的代码",
        "gather_data": "获取财务数据",
        "sentiment": "分析市场情绪",
        "supervisor": "任务调度",
        "synthesis": "生成分析报告",
        "reflect": "报告质量检查",
        "render_output": "渲染最终报告",
        "chat": "生成回复",
        "advance_queue": "推进任务队列",
    }

    async def _stream():
        import asyncio
        from app.harness.task_spec import TaskSpecStore
        from app.harness.task_memory import TaskMemory
        from app.harness.cycle_runtime import CycleRuntime, CycleResult as CR

        # Validate task
        store = await TaskSpecStore.create()
        spec = await store.get_task(user_id, task_id)
        await store.close()
        if not spec or spec.status != "active":
            err = f"Task {task_id} not found or not active"
            yield f"data: {json.dumps({'type': 'error', 'message': err})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Setup graph with event streaming
        from app.dependencies import get_compiled_graph, get_fresh_callbacks
        from app.memory.store import make_thread_config
        import time as _time

        cycle_id = CR.new_id()
        started_at = _time.time()

        graph = get_compiled_graph()
        gconfig = make_thread_config()
        session_id = gconfig["configurable"]["thread_id"]
        callbacks, tracker, journal = get_fresh_callbacks(
            session_id=session_id, user_id=spec.user_id,
            run_tags=["task_cycle", f"task:{task_id}"],
            run_metadata={"intent": "task_cycle", "task_id": task_id},
        )
        run_config = {
            **gconfig,
            "callbacks": callbacks,
            "tags": ["task_cycle", f"task:{task_id}", f"user:{spec.user_id}"],
            "metadata": {"session_id": session_id, "user_id": spec.user_id, "intent": "task_cycle", "task_id": task_id},
        }
        runtime = CycleRuntime(timeout_seconds=settings.cycle_timeout_seconds)
        initial_state = runtime._build_initial_state(spec, session_id, None)

        # Stream graph events
        seen_nodes: set[str] = set()
        try:
            async for event in graph.astream_events(
                initial_state, config=run_config, version="v2",
            ):
                kind = event.get("event", "")
                if kind == "on_chain_start":
                    node = (event.get("metadata") or {}).get("langgraph_node", "")
                    if node and node not in seen_nodes:
                        seen_nodes.add(node)
                        label = _STEP_LABELS.get(node, node)
                        payload = json.dumps(
                            {"type": "step", "node": node, "label": label},
                            ensure_ascii=False,
                        )
                        yield f"data: {payload}\n\n"
                elif kind == "on_tool_start":
                    tool_name = event.get("name", "")
                    if tool_name:
                        payload = json.dumps(
                            {"type": "tool", "tool": tool_name},
                            ensure_ascii=False,
                        )
                        yield f"data: {payload}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'type': 'error', 'message': '执行超时'})}\n\n"
            yield "data: [DONE]\n\n"
            return
        except Exception as exc:
            logger.error("Cycle stream failed: %s", exc, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Flush journal
        try:
            await journal.flush()
        except Exception:
            pass

        # Get final state and process result
        try:
            result_state = await graph.aget_state(gconfig)
            result = await runtime._process_result(
                spec, cycle_id, started_at, result_state.values,
            )
            payload = json.dumps({
                "type": "done",
                "cycle_id": result.cycle_id,
                "task_id": result.task_id,
                "status": result.status,
                "quality_score": result.quality_score,
                "errors": result.errors,
            }, ensure_ascii=False)
            yield f"data: {payload}\n\n"
        except Exception as exc:
            logger.error("Result processing failed: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

        # Run drift check
        try:
            await scheduler._run_drift_check(spec)
        except Exception:
            pass

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.get("/tasks/{user_id}/{task_id}/cycles")
async def list_task_cycles(user_id: str, task_id: str, limit: int = 10):
    """List recent cycle execution history for a task."""
    from app.harness.task_memory import TaskMemory

    mem = await TaskMemory.create()
    history = await mem.get_cycle_history(task_id, limit=limit)
    await mem.close()
    return {
        "task_id": task_id,
        "cycles": [c.to_dict() for c in history],
        "count": len(history),
    }


@router.get("/tasks/{user_id}/{task_id}/kpi")
async def get_task_kpi(user_id: str, task_id: str, metric: str | None = None, limit: int = 50):
    """Get KPI trajectory for a task."""
    from app.harness.task_memory import TaskMemory

    mem = await TaskMemory.create()
    trajectory = await mem.get_kpi_trajectory(task_id, metric=metric, limit=limit)
    await mem.close()
    return {"task_id": task_id, "trajectory": trajectory, "count": len(trajectory)}


@router.get("/tasks/{user_id}/{task_id}/drift")
async def get_task_drift(user_id: str, task_id: str, unresolved_only: bool = False):
    """Get drift incidents for a task."""
    from app.harness.task_memory import TaskMemory

    mem = await TaskMemory.create()
    incidents = await mem.get_drift_incidents(task_id, unresolved_only=unresolved_only)
    await mem.close()
    return {
        "task_id": task_id,
        "incidents": [
            {"id": d.id, "signal": d.signal, "severity": d.severity,
             "action": d.action, "detected_at": d.detected_at, "resolved": d.resolved}
            for d in incidents
        ],
        "count": len(incidents),
    }


@router.get("/harness/task-dashboard/{task_id}")
async def task_dashboard(task_id: str):
    """Return aggregated task-level metrics."""
    from app.harness.metrics import MetricsAggregator

    try:
        agg = await MetricsAggregator.create()
        data = await agg.task_dashboard(task_id)
        await agg.close()
        return data
    except Exception as exc:
        logger.error("Task dashboard failed: %s", exc, exc_info=True)
        return {"error": str(exc)}


# ═══════════════════════════════════════════════════════════════════════════
#  Data Source Configuration
# ═══════════════════════════════════════════════════════════════════════════

@public_router.get("/llm/providers")
async def list_llm_provider_defs():
    from app.harness.llm_config import list_llm_providers
    providers = list_llm_providers()
    return {"providers": providers, "count": len(providers)}


@router.get("/llm/config/{user_id}")
async def get_llm_config(user_id: str):
    from app.harness.llm_config import serialize_llm_config
    return {"user_id": user_id, "config": serialize_llm_config(user_id)}


@router.put("/llm/config/{user_id}")
async def update_llm_config(user_id: str, body: schemas.LLMConfigItem):
    from app.harness.llm_config import get_llm_config_store, serialize_llm_config

    store = get_llm_config_store()
    store.upsert_config(
        user_id,
        provider=body.provider,
        api_key=body.api_key,
        base_url=body.base_url,
        tool_calling_model=body.tool_calling_model,
        reasoning_model=body.reasoning_model,
        tool_calling_temperature=body.tool_calling_temperature,
        reasoning_temperature=body.reasoning_temperature,
        max_tokens=body.max_tokens,
        enabled=body.enabled,
    )
    return {"user_id": user_id, "config": serialize_llm_config(user_id)}


@router.delete("/llm/config/{user_id}")
async def delete_llm_config(user_id: str):
    from app.harness.llm_config import get_llm_config_store
    deleted = get_llm_config_store().delete_config(user_id)
    return {"deleted": deleted, "user_id": user_id}


@router.post("/llm/test")
async def test_llm_config(body: schemas.LLMTestRequest):
    return await _run_llm_probe(body)

@public_router.get("/datasources")
async def list_datasources():
    """List all 17 supported data source definitions (static metadata)."""
    from app.harness.datasource_config import PROVIDER_CATALOG

    return {
        "providers": [
            {
                "name": m.name,
                "display_name": m.display_name,
                "description": m.description,
                "categories": m.categories,
                "requires_key": m.requires_key,
                "signup_url": m.signup_url,
                "free_tier": m.free_tier,
                "implemented": m.implemented,
            }
            for m in PROVIDER_CATALOG.values()
        ],
        "count": len(PROVIDER_CATALOG),
    }


@router.get("/datasources/config/{user_id}")
async def get_datasource_config(user_id: str):
    """Get merged data source configuration for a user (API keys masked)."""
    from app.harness.datasource_config import (
        PROVIDER_CATALOG,
        get_datasource_config_store,
        mask_api_key,
    )

    store = get_datasource_config_store()
    effective = store.get_effective_config(user_id)

    items = []
    for pname, meta in PROVIDER_CATALOG.items():
        eff = effective.get(pname, {})
        api_key = eff.get("api_key", "")
        items.append({
            "provider_name": pname,
            "display_name": meta.display_name,
            "has_key": bool(api_key),
            "api_key_masked": mask_api_key(api_key),
            "enabled": eff.get("enabled", True),
            "priority_overrides": eff.get("priority_overrides", {}),
            "source": eff.get("source", "default"),
            "implemented": meta.implemented,
        })

    return {"user_id": user_id, "configs": items, "count": len(items)}


@router.put("/datasources/config/{user_id}")
async def update_datasource_config(user_id: str, body: schemas.DataSourceConfigUpdate):
    """Batch update data source configs for a user (or __global__)."""
    from app.harness.datasource_config import get_datasource_config_store, mask_api_key

    store = get_datasource_config_store()
    configs_payload = [c.model_dump() for c in body.configs]
    results = store.batch_upsert(user_id, configs_payload)

    return {
        "user_id": user_id,
        "updated": [
            {
                "provider_name": r["provider_name"],
                "enabled": r["enabled"],
                "api_key_masked": mask_api_key(r.get("api_key", "")),
                "priority_overrides": r.get("priority_overrides", {}),
            }
            for r in results
        ],
        "count": len(results),
    }


@router.delete("/datasources/config/{user_id}/{provider}")
async def delete_datasource_config(user_id: str, provider: str):
    """Delete a single provider config for a user."""
    from app.harness.datasource_config import get_datasource_config_store

    store = get_datasource_config_store()
    deleted = store.delete_config(user_id, provider)
    return {"deleted": deleted, "user_id": user_id, "provider": provider}


@router.get("/datasources/priority/{user_id}")
async def get_datasource_priority(user_id: str, category: str = "fundamental"):
    """Get the effective provider priority list for a category."""
    from app.harness.datasource_config import CATEGORIES, get_datasource_config_store

    if category not in CATEGORIES:
        from fastapi import HTTPException
        raise HTTPException(400, f"Invalid category: {category}. Must be one of {CATEGORIES}")

    store = get_datasource_config_store()
    ordered = store.get_provider_priority(user_id, category)
    return {"user_id": user_id, "category": category, "providers": ordered}


@router.post("/datasources/test/{provider}")
async def test_datasource(provider: str, body: schemas.DataSourceTestRequest):
    """Test connectivity for a data source provider."""
    import time

    from app.harness.datasource_config import PROVIDER_CATALOG
    from app.providers.registry import get_provider

    if provider not in PROVIDER_CATALOG:
        return {"provider": provider, "success": False, "message": f"Unknown provider: {provider}"}

    meta = PROVIDER_CATALOG[provider]
    if not meta.implemented:
        return {"provider": provider, "success": False, "message": "Provider not yet implemented (skeleton only)"}

    start = time.time()
    try:
        p = get_provider(provider, api_key=body.api_key or None)
        # Probe using a method suitable for provider category.
        if "fundamental" in meta.categories:
            result = p.get_company_profile("AAPL")
            success = bool(result and isinstance(result, dict) and (result.get("symbol") or result.get("name")))
        elif "news" in meta.categories:
            result = p.get_company_news("AAPL", limit=1)
            success = bool(isinstance(result, list) and len(result) > 0)
        elif "macro" in meta.categories:
            result = p.get_macro_data("GDP")
            success = bool(result)
        else:
            result = {}
            success = False

        latency = (time.time() - start) * 1000
        if success:
            return {"provider": provider, "success": True, "message": "连接成功", "latency_ms": round(latency, 1)}
        return {"provider": provider, "success": False, "message": "Connected but returned empty data", "latency_ms": round(latency, 1)}
    except NotImplementedError:
        return {"provider": provider, "success": False, "message": "Provider method not yet implemented"}
    except Exception as exc:
        latency = (time.time() - start) * 1000
        return {"provider": provider, "success": False, "message": str(exc)[:200], "latency_ms": round(latency, 1)}
