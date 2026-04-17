"""Atlas Agent Harness — the operating system layer around the LLM.

This package provides infrastructure that wraps every LLM invocation:

* **context**        – Token budget management (the agent's "RAM manager")
* **compaction**     – Conversation & tool-output compression
* **tool_output**    – Tool result truncation and validation
* **recovery**       – Multi-level error recovery chain
* **circuit_breaker** – External-API circuit breaker
* **permissions**    – Tool permission tiers & guards
* **long_term_memory** – Cross-session persistent memory
* **user_store**     – Lightweight user account persistence
* **run_journal**    – Structured per-run decision audit log
* **metrics**        – Aggregated dashboard / resume metrics
* **task_spec**      – Autonomous task contract definitions
* **task_memory**    – Task lifecycle memory (cycles, KPI, drift)
* **cycle_runtime**  – Single-cycle autonomous execution engine
* **drift_detector** – Long-term goal deviation detection
* **rate_limiter**   – Per-run global tool invocation rate limiter
* **scheduler**      – Recurring task scheduling (Phase 2)
* **datasource_config** – Per-user data-source API key & priority config
"""

from app.harness.context import TokenBudgetManager
from app.harness.compaction import compact_conversation
from app.harness.tool_output import truncate_tool_output, validate_tool_output
from app.harness.circuit_breaker import CircuitBreaker, get_breaker
from app.harness.recovery import RecoveryChain, recoverable, ProviderHealthTracker, get_provider_health_tracker
from app.harness.permissions import ToolPermissionGuard, ToolTier, get_permission_guard
from app.harness.rate_limiter import ToolRateLimiter
from app.harness.run_journal import RunJournal, JournalCallback
from app.harness.metrics import MetricsAggregator
from app.harness.task_spec import TaskSpec, TaskSpecStore
from app.harness.task_memory import CycleResult, TaskMemory, DriftIncident
from app.harness.cycle_runtime import CycleRuntime
from app.harness.drift_detector import DriftDetector, DriftSignal
from app.harness.scheduler import TaskScheduler
from app.harness.user_store import UserStore
from app.harness.datasource_config import DataSourceConfigStore, get_datasource_config_store

__all__ = [
    # Phase 1 — Context Engineering
    "TokenBudgetManager",
    "compact_conversation",
    "truncate_tool_output",
    "validate_tool_output",
    # Phase 2 — Error Recovery
    "CircuitBreaker",
    "get_breaker",
    "RecoveryChain",
    "recoverable",
    "ProviderHealthTracker",
    "get_provider_health_tracker",
    # Phase 3 — Tool Guardrails
    "ToolPermissionGuard",
    "ToolTier",
    "get_permission_guard",
    "ToolRateLimiter",
    # Phase 4 — User Persistence
    "UserStore",
    # Phase 5 — Run Journal
    "RunJournal",
    "JournalCallback",
    # Phase 7 — Metrics
    "MetricsAggregator",
    # Task Lifecycle
    "TaskSpec",
    "TaskSpecStore",
    "CycleResult",
    "TaskMemory",
    "DriftIncident",
    "CycleRuntime",
    "DriftDetector",
    "DriftSignal",
    "TaskScheduler",
    # Data Source Configuration
    "DataSourceConfigStore",
    "get_datasource_config_store",
]
