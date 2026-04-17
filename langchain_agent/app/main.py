"""FastAPI application entry point."""

from __future__ import annotations

import logging
import traceback
from contextlib import asynccontextmanager

from starlette.types import ASGIApp, Receive, Scope, Send

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import public_router, router
from app.config import get_settings


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _setup_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    logger.info(
        "Atlas LangChain Agent starting  provider=%s  port=%d",
        settings.llm_provider.value,
        settings.port,
    )

    settings.ensure_monitor_importable()
    settings.ensure_cache_dir()

    # --- LangSmith tracing (opt-in) ---
    if settings.langchain_tracing_v2 and settings.langchain_api_key:
        import os
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
        logger.info(
            "LangSmith tracing ENABLED  project=%s  endpoint=%s",
            settings.langchain_project, settings.langsmith_endpoint,
        )
    else:
        logger.info("LangSmith tracing disabled (set LANGCHAIN_TRACING_V2=true + LANGCHAIN_API_KEY to enable)")

    from app.memory.store import init_checkpointer, close_checkpointer
    from app.memory.watchlist import init_watchlist_table

    await init_checkpointer()
    await init_watchlist_table()

    # --- Monitor pool: build cache in background if missing ---
    import asyncio
    from app.providers.monitor_pool_builder import monitor_cache_exists, build_all_pools

    if not monitor_cache_exists("us_stock"):
        logger.info("Monitor cache missing — launching background pool build")

        async def _bg_build():
            try:
                result = await asyncio.to_thread(build_all_pools)
                logger.info("Background monitor pool build done: %s", result)
            except Exception as exc:
                logger.warning("Background monitor pool build failed: %s", exc)

        asyncio.create_task(_bg_build())
    else:
        logger.info("Monitor cache found — skipping pool build")

    # --- Task Lifecycle Scheduler ---
    from app.harness.scheduler import TaskScheduler
    from app.harness.resident_agent import ResidentAgentService
    from app.harness.pool_refresh import PoolRefreshScheduler

    scheduler = TaskScheduler(cycle_timeout=settings.cycle_timeout_seconds)
    if settings.scheduler_enabled:
        await scheduler.start()
    app.state.scheduler = scheduler
    resident_agent_service = ResidentAgentService(
        cycle_timeout=settings.cycle_timeout_seconds,
        default_interval_seconds=settings.resident_default_interval_seconds,
    )
    await resident_agent_service.start()
    app.state.resident_agent_service = resident_agent_service

    # --- Daily Monitor-Pool Refresh (APScheduler) ---
    pool_refresh = PoolRefreshScheduler(
        timezone=settings.pool_refresh_timezone,
        us_cron=settings.pool_refresh_us_cron,
        etf_cron=settings.pool_refresh_etf_cron,
        hk_cron=settings.pool_refresh_hk_cron,
    )
    if settings.pool_refresh_enabled:
        await pool_refresh.start()
    app.state.pool_refresh = pool_refresh

    yield

    logger.info("Atlas LangChain Agent shutting down")
    await pool_refresh.stop()
    await resident_agent_service.stop()
    if settings.scheduler_enabled:
        await scheduler.stop()
    await close_checkpointer()


app = FastAPI(
    title="Atlas Fundamental Analysis Agent",
    description="LangChain-based multi-agent fundamental stock analysis API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content={"error": str(exc), "code": 400, "detail": "Bad request"},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.getLogger(__name__).error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "code": 500,
            "detail": str(exc),
        },
    )


class _CORSMiddleware:
    """Raw ASGI CORS middleware — works on Python 3.14 where Starlette
    CORSMiddleware silently fails to intercept OPTIONS preflight."""

    CORS_HEADERS = [
        (b"access-control-allow-origin", b"*"),
        (b"access-control-allow-methods", b"GET, POST, PUT, DELETE, OPTIONS, PATCH"),
        (b"access-control-allow-headers", b"*"),
        (b"access-control-max-age", b"86400"),
    ]

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Preflight → respond immediately with 204
        if scope["method"] == "OPTIONS":
            await send({
                "type": "http.response.start",
                "status": 204,
                "headers": self.CORS_HEADERS,
            })
            await send({"type": "http.response.body", "body": b""})
            return

        # Normal request → inject CORS headers
        async def _send(event: dict) -> None:
            if event["type"] == "http.response.start":
                headers = list(event.get("headers", []))
                headers.extend(self.CORS_HEADERS)
                event = {**event, "headers": headers}
            await send(event)

        await self.app(scope, receive, _send)


app.add_middleware(_CORSMiddleware)

app.include_router(public_router)
app.include_router(router)


@app.get("/")
async def root():
    return {
        "service": "Atlas Fundamental Analysis Agent",
        "docs": "/docs",
        "health": "/api/v1/health",
    }


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
