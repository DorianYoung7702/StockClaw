"""Tool Permission Tiers & Guards — controlled tool execution.

Every tool is assigned a permission tier that determines how the harness
handles its invocation:

    read    — auto-execute (data fetching, no side effects)
    compute — auto-execute + log to RunJournal (derived analysis)
    write   — requires human approval via LangGraph interrupt

Usage::

    from app.harness.permissions import ToolPermissionGuard, ToolTier

    guard = ToolPermissionGuard()
    tier = guard.get_tier("get_company_profile")   # → ToolTier.READ
    tier = guard.get_tier("watchlist_add")          # → ToolTier.WRITE
    guard.check_allowed("get_company_news")         # → True
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ToolTier(str, Enum):
    """Permission level for a tool."""
    READ = "read"           # data fetch, no side effects
    COMPUTE = "compute"     # derived analysis, heavier but safe
    WRITE = "write"         # state-mutating, needs approval


# ---------------------------------------------------------------------------
# Static tier registry — maps tool name → tier
# ---------------------------------------------------------------------------

_TOOL_TIERS: dict[str, ToolTier] = {
    # --- Read tier (auto-execute) ---
    "get_company_profile": ToolTier.READ,
    "get_key_metrics": ToolTier.READ,
    "get_financial_statements": ToolTier.READ,
    "get_company_news": ToolTier.READ,
    "get_policy_events": ToolTier.READ,
    "get_price_history": ToolTier.READ,
    "get_market_overview": ToolTier.READ,
    "get_strong_stocks": ToolTier.READ,
    "get_watchlist": ToolTier.READ,
    "get_monitoring_alerts": ToolTier.READ,
    "web_search": ToolTier.READ,
    "duckduckgo_search": ToolTier.READ,

    # --- Compute tier (auto-execute + journal log) ---
    "get_peer_comparison": ToolTier.COMPUTE,
    "get_risk_metrics": ToolTier.COMPUTE,
    "get_catalysts": ToolTier.COMPUTE,
    "get_technical_analysis": ToolTier.COMPUTE,

    # --- Write tier (requires human approval) ---
    # Currently none — watchlist_add is handled by a graph node, not a tool.
    # Future: trade execution tools would go here.
}


# ---------------------------------------------------------------------------
# Permission Guard
# ---------------------------------------------------------------------------

class ToolPermissionGuard:
    """Checks whether a tool invocation is allowed at the current trust level.

    Default behaviour:
    - ``read`` and ``compute`` tools are always allowed.
    - ``write`` tools return ``False`` from ``check_allowed()`` — the caller
      (typically the harness loop) should trigger a LangGraph interrupt.

    Override ``auto_approve_writes=True`` in dev/test to skip approval.
    """

    def __init__(self, *, auto_approve_writes: bool = False) -> None:
        self.auto_approve_writes = auto_approve_writes
        self._overrides: dict[str, ToolTier] = {}

    def register_tier(self, tool_name: str, tier: ToolTier) -> None:
        """Override or register a tier for a tool at runtime."""
        self._overrides[tool_name] = tier

    def get_tier(self, tool_name: str) -> ToolTier:
        """Return the permission tier for *tool_name*.

        Falls back to ``READ`` for unknown tools (safe default).
        """
        return self._overrides.get(tool_name) or _TOOL_TIERS.get(tool_name, ToolTier.READ)

    def check_allowed(self, tool_name: str) -> bool:
        """Return True if the tool can be executed without human approval."""
        tier = self.get_tier(tool_name)
        if tier == ToolTier.WRITE and not self.auto_approve_writes:
            logger.info(
                "ToolPermissionGuard: tool '%s' (tier=%s) requires approval",
                tool_name,
                tier.value,
            )
            return False
        return True

    def check_and_log(self, tool_name: str) -> dict[str, Any]:
        """Check permission and return a log-friendly dict.

        Returns::

            {"tool": name, "tier": "read"|"compute"|"write",
             "allowed": bool, "needs_approval": bool}
        """
        tier = self.get_tier(tool_name)
        allowed = self.check_allowed(tool_name)
        entry = {
            "tool": tool_name,
            "tier": tier.value,
            "allowed": allowed,
            "needs_approval": tier == ToolTier.WRITE and not self.auto_approve_writes,
        }
        if tier == ToolTier.COMPUTE:
            logger.info("ToolPermission: compute-tier tool '%s' executed", tool_name)
        return entry


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_guard: ToolPermissionGuard | None = None


def get_permission_guard() -> ToolPermissionGuard:
    """Return the singleton permission guard."""
    global _guard
    if _guard is None:
        _guard = ToolPermissionGuard()
    return _guard
