"""Circuit Breaker — protects against cascading external-API failures.

When an external data source (yfinance, FMP, OpenBB) fails consecutively,
the breaker trips to OPEN and short-circuits subsequent calls with a
fallback value until a cooldown period expires.

States::

    CLOSED  →  normal operation; failures increment counter
    OPEN    →  all calls short-circuit to fallback
    HALF_OPEN → one probe call allowed; success → CLOSED, fail → OPEN

Usage::

    breaker = get_breaker("yfinance")
    if breaker.allow_request():
        try:
            result = yfinance.download(...)
            breaker.record_success()
        except Exception:
            breaker.record_failure()
            raise
    else:
        # use fallback
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Per-service circuit breaker with configurable thresholds.

    Thread-safe — uses a lock for state transitions so concurrent requests
    don't race on failure counting.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        cooldown_seconds: int = 60,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

        self._state = BreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()

        # Metrics (for RunJournal)
        self.total_trips = 0
        self.total_calls = 0
        self.total_blocked = 0

    @property
    def state(self) -> BreakerState:
        with self._lock:
            return self._current_state()

    def _current_state(self) -> BreakerState:
        """Evaluate state (must be called under lock)."""
        if self._state == BreakerState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.cooldown_seconds:
                self._state = BreakerState.HALF_OPEN
                logger.info(
                    "CircuitBreaker[%s]: OPEN → HALF_OPEN after %.0fs cooldown",
                    self.name,
                    elapsed,
                )
        return self._state

    def allow_request(self) -> bool:
        """Return True if a request should proceed; False if short-circuited."""
        with self._lock:
            self.total_calls += 1
            state = self._current_state()
            if state == BreakerState.CLOSED:
                return True
            if state == BreakerState.HALF_OPEN:
                return True  # probe request
            # OPEN — block
            self.total_blocked += 1
            logger.debug(
                "CircuitBreaker[%s]: OPEN — blocking request (blocked=%d)",
                self.name,
                self.total_blocked,
            )
            return False

    def record_success(self) -> None:
        """Record a successful call — resets failure counter."""
        with self._lock:
            if self._state in (BreakerState.HALF_OPEN, BreakerState.OPEN):
                logger.info(
                    "CircuitBreaker[%s]: %s → CLOSED (success)",
                    self.name,
                    self._state.value,
                )
            self._state = BreakerState.CLOSED
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call — may trip breaker to OPEN."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == BreakerState.HALF_OPEN:
                self._state = BreakerState.OPEN
                self.total_trips += 1
                logger.warning(
                    "CircuitBreaker[%s]: HALF_OPEN → OPEN (probe failed)",
                    self.name,
                )
            elif self._failure_count >= self.failure_threshold:
                self._state = BreakerState.OPEN
                self.total_trips += 1
                logger.warning(
                    "CircuitBreaker[%s]: CLOSED → OPEN (%d consecutive failures)",
                    self.name,
                    self._failure_count,
                )

    def reset(self) -> None:
        """Force-reset to CLOSED (for testing / admin)."""
        with self._lock:
            self._state = BreakerState.CLOSED
            self._failure_count = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise current state for observability / RunJournal."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._current_state().value,
                "failure_count": self._failure_count,
                "total_trips": self.total_trips,
                "total_calls": self.total_calls,
                "total_blocked": self.total_blocked,
            }


# ---------------------------------------------------------------------------
# Global breaker registry — one breaker per external service
# ---------------------------------------------------------------------------

_registry: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(
    name: str,
    *,
    failure_threshold: int | None = None,
    cooldown_seconds: int | None = None,
) -> CircuitBreaker:
    """Return (or create) the singleton breaker for *name*.

    Default thresholds are read from ``Settings`` on first access.
    """
    with _registry_lock:
        if name not in _registry:
            if failure_threshold is None or cooldown_seconds is None:
                from app.config import get_settings
                settings = get_settings()
                failure_threshold = failure_threshold or settings.harness_circuit_breaker_threshold
                cooldown_seconds = cooldown_seconds or settings.harness_circuit_breaker_cooldown

            _registry[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                cooldown_seconds=cooldown_seconds,
            )
        return _registry[name]


def all_breakers() -> dict[str, dict[str, Any]]:
    """Return status of all registered breakers (for observability)."""
    with _registry_lock:
        return {name: cb.to_dict() for name, cb in _registry.items()}
