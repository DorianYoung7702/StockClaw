"""Tool output truncation and validation.

Every tool result passes through this layer before entering the LLM context.
It enforces a character budget, validates JSON parsability, and standardises
the output envelope.

Usage::

    from app.harness.tool_output import truncate_tool_output, validate_tool_output

    clean = truncate_tool_output(raw_output, max_chars=4000)
    validated = validate_tool_output(raw_output)
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default character limit for a single tool's output
DEFAULT_MAX_CHARS: int = 4_000

# When truncating JSON arrays, keep at most this many items
DEFAULT_MAX_ARRAY_ITEMS: int = 5

# --- Tiered limits: tool name → max chars -----------------------------------
# High-value tools (core financial data): generous budget
# Standard tools: default budget
# Low-priority tools (supplementary info): tighter budget
_TIER_HIGH: int = 6_000
_TIER_LOW: int = 2_500

_TOOL_CHAR_TIERS: dict[str, int] = {
    # High tier — core financial data
    "get_financial_statements": _TIER_HIGH,
    "get_key_metrics": _TIER_HIGH,
    "get_company_profile": _TIER_HIGH,
    "get_peer_comparison": _TIER_HIGH,
    "get_risk_metrics": _TIER_HIGH,
    "get_technical_analysis": _TIER_HIGH,
    # Low tier — supplementary / volatile
    "get_company_news": _TIER_LOW,
    "web_search": _TIER_LOW,
    "duckduckgo_search": _TIER_LOW,
    "get_policy_events": _TIER_LOW,
}


def get_tool_char_budget(tool_name: str) -> int:
    """Return the character budget for a tool based on its tier."""
    return _TOOL_CHAR_TIERS.get(tool_name, DEFAULT_MAX_CHARS)


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

def truncate_tool_output(
    raw: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_array_items: int = DEFAULT_MAX_ARRAY_ITEMS,
) -> str:
    """Truncate a tool output string to fit within *max_chars*.

    Strategies (in order):
    1. If *raw* is valid JSON array → keep first *max_array_items* elements +
       append a count annotation.
    2. If *raw* is valid JSON object → try to trim large nested arrays/strings.
    3. Plain text → hard truncate with ``[…已截断]`` marker.

    Returns the (possibly shortened) string.
    """
    if not raw:
        return raw

    if len(raw) <= max_chars:
        return raw

    # --- Strategy 1: JSON array truncation --------------------------------
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and len(parsed) > max_array_items:
            total = len(parsed)
            truncated = parsed[:max_array_items]
            result = json.dumps(truncated, ensure_ascii=False, indent=None)
            annotation = f'\n[... 共 {total} 条，已截断为前 {max_array_items} 条]'
            logger.debug(
                "truncate_tool_output: JSON array %d → %d items",
                total,
                max_array_items,
            )
            return result + annotation

        # --- Strategy 2: JSON object — trim large values ------------------
        if isinstance(parsed, dict):
            trimmed = _trim_json_object(parsed, max_chars)
            result = json.dumps(trimmed, ensure_ascii=False, indent=None)
            if len(result) <= max_chars:
                return result
            # Fall through to hard truncate if still too long
    except (json.JSONDecodeError, TypeError):
        pass

    # --- Strategy 3: hard truncate ----------------------------------------
    cutoff = max_chars - 50  # leave room for the marker
    logger.debug(
        "truncate_tool_output: hard truncate %d → %d chars",
        len(raw),
        cutoff,
    )
    return raw[:cutoff] + f"\n[…已截断，原始 {len(raw)} 字符]"


def _trim_json_object(obj: dict, max_chars: int) -> dict:
    """Recursively trim large string values and arrays inside a JSON object."""
    result: dict[str, Any] = {}
    budget = max_chars
    for key, value in obj.items():
        if budget <= 0:
            result[key] = "[…已省略]"
            continue
        if isinstance(value, str) and len(value) > 500:
            result[key] = value[:500] + "…"
            budget -= 500
        elif isinstance(value, list) and len(value) > DEFAULT_MAX_ARRAY_ITEMS:
            result[key] = value[:DEFAULT_MAX_ARRAY_ITEMS]
            budget -= len(json.dumps(result[key], ensure_ascii=False))
        elif isinstance(value, dict):
            result[key] = _trim_json_object(value, max(500, budget // 2))
            budget -= len(json.dumps(result[key], ensure_ascii=False))
        else:
            result[key] = value
            budget -= len(str(value))
    return result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_tool_output(raw: str) -> dict[str, Any]:
    """Validate and wrap tool output in a standard envelope.

    Returns::

        {"status": "ok"|"error", "data": <parsed_or_raw>, "truncated": bool}
    """
    truncated = False
    data: Any = raw

    # Try JSON parse
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass  # keep raw string

    # Check size
    if len(raw) > DEFAULT_MAX_CHARS:
        data_str = truncate_tool_output(raw)
        try:
            data = json.loads(data_str)
        except (json.JSONDecodeError, TypeError):
            data = data_str
        truncated = True

    return {
        "status": "ok",
        "data": data,
        "truncated": truncated,
        "original_chars": len(raw),
    }


# ---------------------------------------------------------------------------
# Tool wrapper factory (for use with LangChain tool definitions)
# ---------------------------------------------------------------------------

def make_truncating_wrapper(tool_func, *, max_chars: int = DEFAULT_MAX_CHARS):
    """Wrap a LangChain tool function so its output is auto-truncated.

    This is a transparent wrapper — the tool's signature and metadata are
    preserved.  Use it when constructing ReAct agent tool lists::

        tools = [make_truncating_wrapper(get_company_news)]

    If *tool_func* is already a LangChain ``BaseTool`` instance, a new
    ``StructuredTool`` is returned so that ``ToolNode`` recognises it
    directly and skips ``create_tool()`` / ``inspect.signature()``, which
    crashes on Python 3.14 when ``__wrapped__`` points to a StructuredTool.
    """
    from langchain_core.tools import BaseTool, StructuredTool

    if isinstance(tool_func, BaseTool):
        # Build a proper StructuredTool so ToolNode takes the fast path
        # (isinstance check) instead of re-introspecting via inspect.signature.
        original_func = tool_func.func  # the raw callable, NOT ._run()
        # Use tiered budget if caller didn't override
        effective_limit = max_chars if max_chars != DEFAULT_MAX_CHARS else get_tool_char_budget(tool_func.name)

        def _truncated_run(*args: Any, **kwargs: Any) -> Any:
            result = original_func(*args, **kwargs)
            if isinstance(result, str):
                return truncate_tool_output(result, max_chars=effective_limit)
            return result

        return StructuredTool(
            name=tool_func.name,
            description=tool_func.description,
            func=_truncated_run,
            args_schema=tool_func.args_schema,
        )

    # Plain callable fallback
    import functools
    tool_name = getattr(tool_func, "name", getattr(tool_func, "__name__", ""))
    effective_limit = max_chars if max_chars != DEFAULT_MAX_CHARS else get_tool_char_budget(tool_name)

    @functools.wraps(tool_func)
    def wrapper(*args, **kwargs):
        result = tool_func(*args, **kwargs)
        if isinstance(result, str):
            return truncate_tool_output(result, max_chars=effective_limit)
        return result

    # Preserve LangChain tool attributes
    for attr in ("name", "description", "args_schema", "return_direct"):
        if hasattr(tool_func, attr):
            setattr(wrapper, attr, getattr(tool_func, attr))

    return wrapper
