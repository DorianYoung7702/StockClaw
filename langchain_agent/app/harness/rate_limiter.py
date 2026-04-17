"""Global Tool Rate Limiter — prevents runaway tool invocations.

Enforces two limits per graph run:

1. **Per-tool limit** — no single tool can be called more than N times
2. **Global limit** — total tool calls across all tools are capped

Usage::

    from app.harness.rate_limiter import ToolRateLimiter

    limiter = ToolRateLimiter(global_limit=30, per_tool_limit=10)
    if limiter.allow("get_company_profile"):
        # proceed with tool call
    else:
        # skip or degrade
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ToolRateLimiter:
    """Per-run tool invocation rate limiter.

    Create one instance per graph run. Thread-safe within a single
    async task (no concurrent mutations).
    """

    def __init__(
        self,
        *,
        global_limit: int = 40,
        per_tool_limit: int = 12,
        overrides: dict[str, int] | None = None,
    ) -> None:
        self.global_limit = global_limit
        self.per_tool_limit = per_tool_limit
        self._overrides = overrides or {}
        self._counts: dict[str, int] = {}
        self._total: int = 0
        self._rejections: list[dict[str, Any]] = []

    def allow(self, tool_name: str) -> bool:
        """Return True if the tool call is within limits."""
        tool_limit = self._overrides.get(tool_name, self.per_tool_limit)
        tool_count = self._counts.get(tool_name, 0)

        if self._total >= self.global_limit:
            self._rejections.append({
                "tool": tool_name, "reason": "global_limit",
                "current": self._total, "limit": self.global_limit,
            })
            logger.warning(
                "ToolRateLimiter: REJECTED '%s' — global limit %d reached",
                tool_name, self.global_limit,
            )
            return False

        if tool_count >= tool_limit:
            self._rejections.append({
                "tool": tool_name, "reason": "per_tool_limit",
                "current": tool_count, "limit": tool_limit,
            })
            logger.warning(
                "ToolRateLimiter: REJECTED '%s' — per-tool limit %d reached",
                tool_name, tool_limit,
            )
            return False

        # Record the call
        self._counts[tool_name] = tool_count + 1
        self._total += 1
        return True

    @property
    def total(self) -> int:
        """Total tool calls made so far."""
        return self._total

    @property
    def rejections(self) -> list[dict[str, Any]]:
        """List of rejected tool calls for diagnostics."""
        return self._rejections

    def summary(self) -> dict[str, Any]:
        """Return a summary dict for RunJournal / metrics."""
        return {
            "total_calls": self._total,
            "global_limit": self.global_limit,
            "per_tool_counts": dict(self._counts),
            "rejections": len(self._rejections),
        }
