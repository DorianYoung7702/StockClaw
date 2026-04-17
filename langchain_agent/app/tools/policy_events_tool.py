"""Tool for fetching upcoming macro / policy events."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PolicyEventsInput(BaseModel):
    horizon_days: int = Field(
        default=90,
        description="Number of days ahead to look for upcoming events (default 90)",
    )


@tool("get_policy_events", args_schema=PolicyEventsInput)
def get_policy_events(horizon_days: int = 90) -> str:
    """Fetch upcoming macro-economic and policy events (FOMC, CPI, NFP, GDP, etc.).

    Returns a JSON array of events with date, label, days_away, and detail.
    Use this to understand the macro backdrop when analysing a stock's sentiment,
    especially when company-specific news is scarce.
    """
    from app.providers.policy_events import get_upcoming_policy_events

    events = get_upcoming_policy_events(horizon_days=horizon_days)
    if not events:
        return json.dumps({"message": "No upcoming policy events found within the horizon."})
    return json.dumps(events, default=str, ensure_ascii=False)
