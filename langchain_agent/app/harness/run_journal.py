"""Structured Run Journal — audit trail for every graph invocation.

Every agent run (graph invocation) produces a sequence of ``JournalEntry``
records that capture the full decision trace: which nodes ran, which tools
were called, what errors occurred, how they were recovered, and how many
tokens were consumed.

The journal serves two purposes:
1. **Audit** — every decision is traceable and reproducible.
2. **Metrics** — aggregated journal data feeds the resume dashboard.

Usage::

    journal = RunJournal(run_id="abc", session_id="s1", user_id="u1")
    journal.log("node_start", node="gather_data")
    journal.log("tool_call", node="gather_data", payload={"tool": "get_key_metrics"})
    journal.log("node_end", node="gather_data", latency_ms=1200)

    # Persist at end of run
    await journal.flush(db_path)

    # Or use the callback handler for automatic collection
    cb = JournalCallback(journal)
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Journal Entry
# ---------------------------------------------------------------------------

@dataclass
class JournalEntry:
    """One event in the run's decision trace."""
    timestamp: float = field(default_factory=time.time)
    event_type: str = ""       # node_start|node_end|tool_call|tool_result|
                               # llm_call|llm_end|error|recovery|compaction|approval
    node: str = ""
    payload: dict = field(default_factory=dict)
    token_usage: Optional[dict] = None
    latency_ms: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "node": self.node,
        }
        if self.payload:
            d["payload"] = self.payload
        if self.token_usage:
            d["token_usage"] = self.token_usage
        if self.latency_ms is not None:
            d["latency_ms"] = round(self.latency_ms, 1)
        return d


# ---------------------------------------------------------------------------
# Run Journal
# ---------------------------------------------------------------------------

class RunJournal:
    """Collects journal entries for a single graph invocation (run).

    Thread-safe: entries are appended atomically via list.append.
    """

    def __init__(
        self,
        run_id: str | None = None,
        session_id: str = "",
        user_id: str = "",
    ) -> None:
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.session_id = session_id
        self.user_id = user_id
        self.entries: list[JournalEntry] = []
        self.started_at: float = time.time()
        self._node_starts: dict[str, float] = {}

    # -- Logging helpers ---------------------------------------------------

    def log(
        self,
        event_type: str,
        *,
        node: str = "",
        payload: dict | None = None,
        token_usage: dict | None = None,
        latency_ms: float | None = None,
    ) -> JournalEntry:
        """Append a journal entry."""
        entry = JournalEntry(
            event_type=event_type,
            node=node,
            payload=payload or {},
            token_usage=token_usage,
            latency_ms=latency_ms,
        )
        self.entries.append(entry)
        return entry

    def node_start(self, node: str) -> None:
        """Record node start (auto-calculates latency on node_end)."""
        self._node_starts[node] = time.perf_counter()
        self.log("node_start", node=node)

    def node_end(self, node: str, **extra: Any) -> None:
        """Record node end with auto-calculated latency."""
        start = self._node_starts.pop(node, None)
        latency = (time.perf_counter() - start) * 1000 if start else None
        self.log("node_end", node=node, latency_ms=latency, payload=extra)

    def tool_call(self, node: str, tool_name: str, **extra: Any) -> None:
        self.log("tool_call", node=node, payload={"tool": tool_name, **extra})

    def tool_result(self, node: str, tool_name: str, chars: int, truncated: bool = False) -> None:
        self.log("tool_result", node=node, payload={
            "tool": tool_name, "output_chars": chars, "truncated": truncated,
        })

    def error(self, node: str, error: str, level: int = 0) -> None:
        self.log("error", node=node, payload={"error": error[:500], "recovery_level": level})

    def recovery(self, node: str, level: int, resolution: str) -> None:
        self.log("recovery", node=node, payload={"level": level, "resolution": resolution})

    def compaction(self, before_tokens: int, after_tokens: int) -> None:
        self.log("compaction", payload={
            "before_tokens": before_tokens, "after_tokens": after_tokens,
            "saved_tokens": before_tokens - after_tokens,
        })

    # -- Summaries ---------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Aggregate metrics for this run."""
        total_latency = sum(
            e.latency_ms for e in self.entries
            if e.latency_ms is not None
        )
        total_tokens = {}
        for e in self.entries:
            if e.token_usage:
                for k, v in e.token_usage.items():
                    total_tokens[k] = total_tokens.get(k, 0) + v

        tool_calls = [e for e in self.entries if e.event_type == "tool_call"]
        errors = [e for e in self.entries if e.event_type == "error"]
        recoveries = [e for e in self.entries if e.event_type == "recovery"]
        compactions = [e for e in self.entries if e.event_type == "compaction"]

        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "started_at": self.started_at,
            "duration_ms": round((time.time() - self.started_at) * 1000, 1),
            "total_entries": len(self.entries),
            "total_latency_ms": round(total_latency, 1),
            "token_usage": total_tokens,
            "tool_calls": len(tool_calls),
            "errors": len(errors),
            "recoveries": len(recoveries),
            "compactions": len(compactions),
            "recovery_levels": [e.payload.get("level") for e in recoveries],
        }

    # -- Persistence -------------------------------------------------------

    async def flush(self, db_path: str | None = None) -> None:
        """Persist all entries to SQLite."""
        import aiosqlite

        if db_path is None:
            from app.config import get_settings
            settings = get_settings()
            db_path = settings.harness_journal_db_path or settings.checkpoint_db_path

        async with aiosqlite.connect(db_path) as conn:
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS run_journal (
                    run_id     TEXT NOT NULL,
                    session_id TEXT,
                    user_id    TEXT,
                    entry_idx  INTEGER NOT NULL,
                    entry_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (run_id, entry_idx)
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_run_journal_session
                ON run_journal (session_id, created_at DESC)
            """)

            rows = [
                (
                    self.run_id,
                    self.session_id,
                    self.user_id,
                    idx,
                    json.dumps(entry.to_dict(), ensure_ascii=False),
                    entry.timestamp,
                )
                for idx, entry in enumerate(self.entries)
            ]
            await conn.executemany(
                "INSERT OR REPLACE INTO run_journal "
                "(run_id, session_id, user_id, entry_idx, entry_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            await conn.commit()
            logger.info(
                "RunJournal[%s]: flushed %d entries to %s",
                self.run_id, len(rows), db_path,
            )

    @classmethod
    async def load(cls, run_id: str, db_path: str | None = None) -> "RunJournal":
        """Load a journal from SQLite by run_id."""
        import aiosqlite

        if db_path is None:
            from app.config import get_settings
            settings = get_settings()
            db_path = settings.harness_journal_db_path or settings.checkpoint_db_path

        journal = cls(run_id=run_id)
        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute(
                "SELECT session_id, user_id, entry_json, created_at "
                "FROM run_journal WHERE run_id = ? ORDER BY entry_idx",
                (run_id,),
            )
            rows = await cursor.fetchall()
            for row in rows:
                journal.session_id = row[0] or ""
                journal.user_id = row[1] or ""
                data = json.loads(row[2])
                journal.entries.append(JournalEntry(
                    timestamp=data.get("timestamp", row[3]),
                    event_type=data.get("event_type", ""),
                    node=data.get("node", ""),
                    payload=data.get("payload", {}),
                    token_usage=data.get("token_usage"),
                    latency_ms=data.get("latency_ms"),
                ))
        return journal


# ---------------------------------------------------------------------------
# LangChain Callback Handler (auto-collects journal entries)
# ---------------------------------------------------------------------------

class JournalCallback(BaseCallbackHandler):
    """LangChain BaseCallbackHandler that writes events to a RunJournal.

    Extends the existing CostTracker/StepLogger pattern — attach this to
    the callback list and it will automatically record LLM and tool events.
    """

    def __init__(self, journal: RunJournal) -> None:
        super().__init__()
        self.journal = journal
        self._call_starts: dict[str, float] = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        rid = str(run_id)
        self._call_starts[rid] = time.perf_counter()
        node = kwargs.get("metadata", {}).get("langgraph_node", "")
        self.journal.log("llm_call", node=node, payload={
            "model": serialized.get("kwargs", {}).get("model", "unknown"),
        })

    def on_llm_end(self, response, *, run_id, **kwargs):
        rid = str(run_id)
        start = self._call_starts.pop(rid, None)
        latency = (time.perf_counter() - start) * 1000 if start else None
        token_usage = {}
        if hasattr(response, "llm_output") and response.llm_output:
            usage = response.llm_output.get("token_usage", {})
            token_usage = {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            }
        self.journal.log("llm_end", latency_ms=latency, token_usage=token_usage or None)

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        name = serialized.get("name", "unknown")
        node = kwargs.get("metadata", {}).get("langgraph_node", "")
        self.journal.tool_call(node, name)

    def on_tool_end(self, output, *, run_id, **kwargs):
        name = kwargs.get("name", "unknown")
        node = kwargs.get("metadata", {}).get("langgraph_node", "")
        out_str = str(output) if output else ""
        self.journal.tool_result(node, name, chars=len(out_str))

    def on_llm_error(self, error, *, run_id, **kwargs):
        node = kwargs.get("metadata", {}).get("langgraph_node", "")
        self.journal.error(node, str(error))

    def on_tool_error(self, error, *, run_id, **kwargs):
        node = kwargs.get("metadata", {}).get("langgraph_node", "")
        self.journal.error(node, str(error))

    def on_custom_event(self, name: str, data: Any, *, run_id, **kwargs) -> None:
        """Capture harness_event custom events into the RunJournal."""
        if name != "harness_event" or not isinstance(data, dict):
            return
        module = data.get("module", "unknown")
        node = data.get("node", kwargs.get("metadata", {}).get("langgraph_node", ""))
        self.journal.log(
            f"harness_{module}",
            node=node,
            payload={k: v for k, v in data.items() if k not in ("module",)},
        )
