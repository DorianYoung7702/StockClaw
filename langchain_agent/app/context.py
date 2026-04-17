"""Request-scoped context variables.

Set once per request (API route / graph invocation), automatically available
to all tools and harness modules without explicit parameter passing.
"""

from __future__ import annotations

from contextvars import ContextVar

# Current authenticated user ID (token hash).  Set by API routes before
# invoking the graph.  Tools read this instead of accepting user_id as a param.
current_user_id: ContextVar[str] = ContextVar("current_user_id", default="default")
