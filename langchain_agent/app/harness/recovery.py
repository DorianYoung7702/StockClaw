"""Multi-level Error Recovery Chain.

Implements the 4-layer recovery hierarchy for agent nodes:

1. **Retry** — exponential back-off (existing ``node_retry`` behaviour)
2. **Fallback Provider** — switch data source (yfinance → FMP → mock)
3. **Degrade** — skip failed sub-agent, let synthesis use partial data
4. **Escalate** — return structured error with suggested user action

Usage::

    from app.harness.recovery import recoverable

    @recoverable(
        max_retry=3,
        fallback_providers=["yfinance", "fmp", "mock"],
        degradable=True,
    )
    async def gather_data_node(state):
        ...
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

try:
    from langchain_core.callbacks import adispatch_custom_event
except ImportError:  # pragma: no cover
    adispatch_custom_event = None  # type: ignore

logger = logging.getLogger(__name__)

# Errors that should never be retried (programming bugs)
_NON_RETRYABLE = (ValueError, KeyError, TypeError, AttributeError)


# ---------------------------------------------------------------------------
# Recovery Event (for RunJournal)
# ---------------------------------------------------------------------------

@dataclass
class RecoveryEvent:
    """One event in the recovery chain — logged to RunJournal."""
    timestamp: float = field(default_factory=time.time)
    level: int = 1  # 1=retry, 2=fallback, 3=degrade, 4=escalate
    level_name: str = "retry"
    node: str = ""
    attempt: int = 0
    error: str = ""
    resolution: str = ""
    suggested_fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "timestamp": self.timestamp,
            "level": self.level,
            "level_name": self.level_name,
            "node": self.node,
            "attempt": self.attempt,
            "error": str(self.error)[:500],
            "resolution": self.resolution,
        }
        if self.suggested_fix:
            d["suggested_fix"] = self.suggested_fix
        return d


# ---------------------------------------------------------------------------
# Suggested fix heuristics
# ---------------------------------------------------------------------------


def _suggest_fix_l1(exc: Exception, attempt: int, max_retry: int) -> str:
    """Generate a contextual fix suggestion for L1 retry errors."""
    err = str(exc).lower()
    if "timeout" in err or "timed out" in err:
        return "Request timed out → retrying with back-off; consider switching provider"
    if "rate" in err and "limit" in err:
        return "Rate limit hit → backing off before retry"
    if "connection" in err or "connect" in err:
        return "Connection error → check network; fallback provider may be needed"
    if "404" in err or "not found" in err:
        return "Resource not found → verify ticker symbol or endpoint"
    if attempt >= max_retry:
        return "All retries exhausted → will try fallback provider or degrade"
    return f"Transient error → retry {attempt}/{max_retry}"


# ---------------------------------------------------------------------------
# Provider Health Tracker (adaptive fallback ordering)
# ---------------------------------------------------------------------------

class ProviderHealthTracker:
    """Track per-provider success/failure rates for adaptive fallback ordering.

    Singleton: use ``get_provider_health_tracker()`` to obtain the instance.

    Health score = successes / (successes + failures) over a sliding window.
    Providers with higher health are tried first during L2 fallback.
    """

    def __init__(self, window_size: int = 50) -> None:
        self._window_size = window_size
        self._records: dict[str, list[bool]] = {}  # provider → [True/False, ...]

    def record(self, provider: str, success: bool) -> None:
        """Record a success/failure for a provider."""
        history = self._records.setdefault(provider, [])
        history.append(success)
        if len(history) > self._window_size:
            history.pop(0)

    def score(self, provider: str) -> float:
        """Return health score (0.0 – 1.0). Unknown providers get 0.5."""
        history = self._records.get(provider)
        if not history:
            return 0.5
        return sum(history) / len(history)

    def rank(self, providers: list[str]) -> list[str]:
        """Return providers sorted by health score (best first)."""
        return sorted(providers, key=lambda p: self.score(p), reverse=True)

    def summary(self) -> dict[str, dict[str, Any]]:
        """Return a summary dict for diagnostics / metrics."""
        return {
            p: {
                "score": round(self.score(p), 3),
                "total": len(h),
                "successes": sum(h),
                "failures": len(h) - sum(h),
            }
            for p, h in self._records.items()
        }


_health_tracker: ProviderHealthTracker | None = None


def get_provider_health_tracker() -> ProviderHealthTracker:
    """Return the singleton health tracker."""
    global _health_tracker
    if _health_tracker is None:
        _health_tracker = ProviderHealthTracker()
    return _health_tracker


# ---------------------------------------------------------------------------
# Recovery Chain
# ---------------------------------------------------------------------------

class RecoveryChain:
    """Orchestrates multi-level error recovery for a single node execution.

    Levels are tried in order (1 → 4); each level logs a RecoveryEvent.
    """

    def __init__(
        self,
        node_name: str,
        *,
        max_retry: int = 3,
        base_delay: float = 1.0,
        timeout_seconds: float | None = None,
        fallback_providers: list[str] | None = None,
        degradable: bool = False,
    ) -> None:
        self.node_name = node_name
        self.max_retry = max_retry
        self.base_delay = base_delay
        self.timeout_seconds = timeout_seconds
        self.fallback_providers = fallback_providers or []
        self.degradable = degradable
        self.events: list[RecoveryEvent] = []

    # -- Level 1: Retry with back-off -------------------------------------

    async def _emit(self, event: RecoveryEvent) -> None:
        """Emit a LangGraph custom event for the SSE stream."""
        if adispatch_custom_event is None:
            return
        try:
            payload: dict[str, Any] = {
                "module": "recovery",
                "level": event.level,
                "level_name": event.level_name,
                "node": event.node,
                "attempt": event.attempt,
                "error": event.error[:200] if event.error else "",
                "resolution": event.resolution,
            }
            if event.suggested_fix:
                payload["suggested_fix"] = event.suggested_fix
            await adispatch_custom_event("harness_event", payload)
        except Exception:
            pass  # never let SSE emission break the recovery chain

    async def _level1_retry(self, func: Callable, state: dict) -> dict | None:
        """Retry the function with exponential back-off."""
        for attempt in range(1, self.max_retry + 1):
            try:
                coro = func(state)
                if self.timeout_seconds is not None:
                    result = await asyncio.wait_for(coro, timeout=self.timeout_seconds)
                else:
                    result = await coro
                if attempt > 1:
                    ev = RecoveryEvent(
                        level=1, level_name="retry", node=self.node_name,
                        attempt=attempt, resolution="succeeded_on_retry",
                    )
                    self.events.append(ev)
                    await self._emit(ev)
                return result
            except _NON_RETRYABLE:
                raise  # never retry programming bugs
            except Exception as exc:
                fix = _suggest_fix_l1(exc, attempt, self.max_retry)
                ev = RecoveryEvent(
                    level=1, level_name="retry", node=self.node_name,
                    attempt=attempt, error=str(exc),
                    resolution="retrying" if attempt < self.max_retry else "exhausted",
                    suggested_fix=fix,
                )
                self.events.append(ev)
                await self._emit(ev)
                logger.warning(
                    "Recovery[%s] L1 attempt %d/%d failed: %s",
                    self.node_name, attempt, self.max_retry, exc,
                )
                if attempt < self.max_retry:
                    delay = self.base_delay * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
        return None  # all retries exhausted

    # -- Level 2: Fallback provider ----------------------------------------

    async def _level2_fallback(self, func: Callable, state: dict) -> dict | None:
        """Try alternate data providers (ordered by health score)."""
        if not self.fallback_providers:
            return None

        tracker = get_provider_health_tracker()
        ranked_providers = tracker.rank(self.fallback_providers)

        for provider_name in ranked_providers:
            try:
                logger.info(
                    "Recovery[%s] L2: trying fallback provider '%s' (health=%.2f)",
                    self.node_name, provider_name, tracker.score(provider_name),
                )
                # Inject provider override into state
                modified_state = dict(state)
                modified_state["_fallback_provider"] = provider_name
                result = await func(modified_state)
                tracker.record(provider_name, True)
                ev = RecoveryEvent(
                    level=2, level_name="fallback", node=self.node_name,
                    resolution=f"fallback_to_{provider_name}",
                )
                self.events.append(ev)
                await self._emit(ev)
                return result
            except Exception as exc:
                tracker.record(provider_name, False)
                ev = RecoveryEvent(
                    level=2, level_name="fallback", node=self.node_name,
                    error=str(exc),
                    resolution=f"fallback_{provider_name}_failed",
                    suggested_fix=f"Provider '{provider_name}' failed → trying next fallback",
                )
                self.events.append(ev)
                await self._emit(ev)
                logger.warning(
                    "Recovery[%s] L2 fallback '%s' failed: %s",
                    self.node_name, provider_name, exc,
                )
        return None

    # -- Level 3: Degrade (skip) -------------------------------------------

    async def _level3_degrade(self, state: dict) -> dict | None:
        """Return a graceful degradation result — skip this node."""
        if not self.degradable:
            return None

        logger.warning(
            "Recovery[%s] L3: degrading — node output will be empty",
            self.node_name,
        )
        ev = RecoveryEvent(
            level=3, level_name="degrade", node=self.node_name,
            resolution="skipped_gracefully",
            suggested_fix=f"Node '{self.node_name}' degraded → synthesis will use partial data",
        )
        self.events.append(ev)
        await self._emit(ev)
        errors: list[str] = list(state.get("errors", []))
        errors.append(f"[{self.node_name}] degraded: all data sources failed, analysis may be incomplete")
        return {
            "errors": errors,
            "current_step": f"{self.node_name}_degraded",
        }

    # -- Level 4: Escalate -------------------------------------------------

    async def _level4_escalate(self, state: dict) -> dict:
        """Return a structured escalation error."""
        logger.error(
            "Recovery[%s] L4: escalating — all recovery levels exhausted",
            self.node_name,
        )
        ev = RecoveryEvent(
            level=4, level_name="escalate", node=self.node_name,
            resolution="escalated_to_user",
            suggested_fix="All recovery levels exhausted → check data source connectivity and retry",
        )
        self.events.append(ev)
        await self._emit(ev)
        errors: list[str] = list(state.get("errors", []))
        errors.append(
            f"[{self.node_name}] ESCALATED: all recovery attempts failed. "
            "Please check data source connectivity and try again."
        )
        return {
            "errors": errors,
            "current_step": f"{self.node_name}_escalated",
        }

    # -- Orchestrator ------------------------------------------------------

    async def execute(self, func: Callable, state: dict) -> dict:
        """Run the full recovery chain: L1 → L2 → L3 → L4."""
        # Level 1: Retry
        result = await self._level1_retry(func, state)
        if result is not None:
            return result

        # Level 2: Fallback provider
        result = await self._level2_fallback(func, state)
        if result is not None:
            return result

        # Level 3: Degrade
        result = await self._level3_degrade(state)
        if result is not None:
            return result

        # Level 4: Escalate (always returns)
        return await self._level4_escalate(state)


# ---------------------------------------------------------------------------
# Decorator (drop-in replacement for node_retry)
# ---------------------------------------------------------------------------

def recoverable(
    *,
    max_retry: int = 3,
    base_delay: float = 1.0,
    timeout_seconds: float | None = None,
    fallback_providers: list[str] | None = None,
    degradable: bool = False,
) -> Callable:
    """Decorator: wrap an async LangGraph node with multi-level recovery.

    This is a superset of the existing ``node_retry`` — Level 1 provides
    identical retry-with-backoff behaviour.  Levels 2-4 are opt-in via
    parameters.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(state: dict, *args: Any, **kwargs: Any) -> dict:
            chain = RecoveryChain(
                node_name=func.__name__,
                max_retry=max_retry,
                base_delay=base_delay,
                timeout_seconds=timeout_seconds,
                fallback_providers=fallback_providers,
                degradable=degradable,
            )
            result = await chain.execute(func, state)
            # Attach recovery events to state for RunJournal
            if chain.events:
                events_list = result.get("_recovery_events", [])
                events_list.extend(e.to_dict() for e in chain.events)
                result["_recovery_events"] = events_list
            return result

        return wrapper

    return decorator
