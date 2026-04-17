"""Custom LangChain callbacks for logging, cost tracking, and LangSmith compatibility."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)


class CostTracker(BaseCallbackHandler):
    """Track token usage and latency for every LLM call.

    Accumulated statistics are available via the ``stats`` property and can be
    sent to Prometheus, Datadog, or simply logged at the end of a request.
    """

    def __init__(self) -> None:
        super().__init__()
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_calls: int = 0
        self.total_tool_calls: int = 0
        self._call_start: dict[UUID, float] = {}
        self.total_latency_ms: float = 0.0

    # -- LLM lifecycle -------------------------------------------------

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._call_start[run_id] = time.perf_counter()
        self.total_calls += 1

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._call_start[run_id] = time.perf_counter()
        self.total_calls += 1

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        start = self._call_start.pop(run_id, None)
        if start is not None:
            self.total_latency_ms += (time.perf_counter() - start) * 1000

        if hasattr(response, "llm_output") and response.llm_output:
            usage = response.llm_output.get("token_usage", {})
            self.total_prompt_tokens += usage.get("prompt_tokens", 0)
            self.total_completion_tokens += usage.get("completion_tokens", 0)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._call_start.pop(run_id, None)
        logger.warning("LLM error in run %s: %s", run_id, error)

    # -- Tool lifecycle ------------------------------------------------

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self.total_tool_calls += 1
        logger.debug("Tool started: %s", serialized.get("name", "unknown"))

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        logger.warning("Tool error in run %s: %s", run_id, error)

    # -- Accessors -----------------------------------------------------

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "total_tool_calls": self.total_tool_calls,
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "total_latency_ms": round(self.total_latency_ms, 1),
        }

    def reset(self) -> None:
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_calls = 0
        self.total_tool_calls = 0
        self._call_start.clear()
        self.total_latency_ms = 0.0


class StepLogger(BaseCallbackHandler):
    """Log each agent step (LLM call, tool call) at INFO level for observability."""

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        model = serialized.get("kwargs", {}).get("model", "unknown")
        logger.info("[step] LLM call started  model=%s  run=%s", model, run_id)

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        logger.info("[step] LLM call finished  run=%s", run_id)

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        name = serialized.get("name", "unknown")
        logger.info("[step] Tool call: %s  run=%s", name, run_id)

    def on_tool_end(self, output: str, *, run_id: UUID, **kwargs: Any) -> None:
        logger.info("[step] Tool finished  run=%s  output_len=%d", run_id, len(str(output)))


def get_default_callbacks(
    *,
    run_metadata: dict[str, Any] | None = None,
) -> list[BaseCallbackHandler]:
    """Return the standard callback set used for every agent invocation.

    When LangSmith tracing is enabled (``LANGCHAIN_TRACING_V2=true``), the
    official ``LangChainTracer`` is appended so that all LLM / tool / chain
    events are automatically reported to the LangSmith dashboard.

    *run_metadata* is merged into every LangSmith run's ``metadata`` field,
    allowing per-request context (session_id, user_id, ticker, intent) to
    appear alongside each trace.
    """
    import os

    cbs: list[BaseCallbackHandler] = [CostTracker(), StepLogger()]

    if os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true":
        try:
            from langchain_core.tracers import LangChainTracer

            cbs.append(LangChainTracer(
                project_name=os.environ.get("LANGCHAIN_PROJECT", "atlas-fundamental-agent"),
                metadata=run_metadata or {},
            ))
        except Exception as exc:  # pragma: no cover
            logger.warning("LangSmith tracer init failed (non-fatal): %s", exc)

    return cbs
