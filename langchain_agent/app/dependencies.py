"""FastAPI dependency injection helpers."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.agents.graph import compile_graph
from app.callbacks.tracing import CostTracker, get_default_callbacks
from app.config import Settings, get_settings
from app.harness.run_journal import RunJournal, JournalCallback
from app.memory.store import get_checkpointer


@lru_cache(maxsize=1)
def get_compiled_graph():
    """Return the singleton compiled LangGraph agent."""
    checkpointer = get_checkpointer()
    return compile_graph(checkpointer=checkpointer)


def get_fresh_callbacks(
    session_id: str = "",
    user_id: str = "",
    *,
    run_tags: list[str] | None = None,
    run_metadata: dict[str, Any] | None = None,
) -> tuple[list, CostTracker, RunJournal]:
    """Create a fresh set of callbacks per request.

    Returns (callbacks, cost_tracker, run_journal).
    The caller must ``await journal.flush()`` after the graph finishes.

    *run_tags* and *run_metadata* are forwarded to LangSmith so each trace
    is annotated with session / user / intent / ticker context.
    """
    # Build LangSmith metadata from explicit args + caller-supplied dict
    meta: dict[str, Any] = {"session_id": session_id, "user_id": user_id}
    if run_metadata:
        meta.update(run_metadata)

    cbs = get_default_callbacks(run_metadata=meta)
    tracker = next(c for c in cbs if isinstance(c, CostTracker))
    journal = RunJournal(session_id=session_id, user_id=user_id)
    cbs.append(JournalCallback(journal))
    return cbs, tracker, journal


def get_app_settings() -> Settings:
    return get_settings()
