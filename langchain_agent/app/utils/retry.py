"""Node-level retry with exponential back-off, timeout, and graceful degradation.

Usage::

    from app.utils.retry import node_retry

    @node_retry(max_attempts=3, timeout_seconds=120)
    async def gather_data_node(state: AgentState) -> dict:
        ...
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

_NON_RETRYABLE = (ValueError, KeyError, TypeError, AttributeError)


def node_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    timeout_seconds: float | None = None,
    fallback: dict[str, Any] | None = None,
) -> Callable:
    """Decorator: wrap an async LangGraph node with retry + optional per-attempt timeout.

    Args:
        max_attempts:    Total attempts (including the first).
        base_delay:      Initial retry delay in seconds; doubles each attempt (exponential back-off).
        timeout_seconds: Per-attempt wall-clock limit. ``None`` = unlimited.
        fallback:        Exact state dict returned when all attempts are exhausted.
                         When ``None``, an entry is appended to ``state["errors"]`` and the
                         node is treated as a soft skip (synthesis can still proceed with
                         whatever data was gathered so far).
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(state: dict, *args: Any, **kwargs: Any) -> dict[str, Any]:
            last_exc: BaseException | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    coro = func(state, *args, **kwargs)
                    if timeout_seconds is not None:
                        result = await asyncio.wait_for(coro, timeout=timeout_seconds)
                    else:
                        result = await coro
                    return result  # success — return immediately

                except _NON_RETRYABLE as exc:
                    logger.error(
                        "Node %s: non-retryable error (won't retry): %s",
                        func.__name__,
                        exc,
                    )
                    raise

                except asyncio.TimeoutError as exc:
                    last_exc = exc
                    logger.warning(
                        "Node %s attempt %d/%d timed out (%.0fs). %s",
                        func.__name__,
                        attempt,
                        max_attempts,
                        timeout_seconds,
                        "Retrying…" if attempt < max_attempts else "Giving up.",
                    )

                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    logger.warning(
                        "Node %s attempt %d/%d failed: %s. %s",
                        func.__name__,
                        attempt,
                        max_attempts,
                        exc,
                        "Retrying…" if attempt < max_attempts else "Giving up.",
                    )

                if attempt < max_attempts:
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.debug("Node %s: sleeping %.1fs before retry", func.__name__, delay)
                    await asyncio.sleep(delay)

            logger.error(
                "Node %s gave up after %d attempts. Last error: %s",
                func.__name__,
                max_attempts,
                last_exc,
            )

            if fallback is not None:
                return fallback

            errors: list[str] = list(state.get("errors", []))
            errors.append(
                f"[{func.__name__}] failed after {max_attempts} attempts: {last_exc}"
            )
            return {
                "errors": errors,
                "current_step": f"{func.__name__}_failed",
            }

        return wrapper

    return decorator
