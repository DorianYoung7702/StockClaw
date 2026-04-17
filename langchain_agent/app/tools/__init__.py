"""All LangChain tools available for agents."""

from app.tools.catalysts import get_catalysts
from app.tools.company_profile import get_company_profile
from app.tools.financial_statements import get_financial_statements
from app.tools.key_metrics import get_key_metrics
from app.tools.market_data import get_market_overview
from app.tools.monitoring_alerts import get_monitoring_alerts
from app.tools.news_sentiment import get_company_news
from app.tools.policy_events_tool import get_policy_events
from app.tools.peer_comparison import get_peer_comparison
from app.tools.price_history import get_price_history
from app.tools.risk_metrics import get_risk_metrics
from app.tools.strong_stocks import get_strong_stocks
from app.tools.technical_analysis import get_technical_analysis
from app.tools.watchlist import get_watchlist, add_to_watchlist, remove_from_watchlist, clear_watchlist
from app.tools.task_management import create_task, list_tasks, delete_task
from app.tools.memory_management import list_memories, delete_memory, clear_memories
from app.tools.resolve_symbol import resolve_symbol
from app.tools.web_search import web_search

ALL_TOOLS = [
    get_financial_statements,
    get_key_metrics,
    get_company_profile,
    get_company_news,
    get_peer_comparison,
    get_risk_metrics,
    get_catalysts,
    get_strong_stocks,
    get_market_overview,
    get_price_history,
    get_watchlist,
    add_to_watchlist,
    remove_from_watchlist,
    clear_watchlist,
    create_task,
    list_tasks,
    delete_task,
    list_memories,
    delete_memory,
    clear_memories,
    resolve_symbol,
    get_technical_analysis,
    get_monitoring_alerts,
    get_policy_events,
]

FUNDAMENTAL_TOOLS = [
    get_financial_statements,
    get_key_metrics,
    get_company_profile,
    get_peer_comparison,
    get_risk_metrics,
    get_catalysts,
    get_price_history,
    get_technical_analysis,
]

SENTIMENT_TOOLS = [
    get_company_news,
    get_company_profile,
    get_policy_events,
    web_search,
]

MARKET_TOOLS = [
    get_strong_stocks,
    get_market_overview,
    get_watchlist,
    get_monitoring_alerts,
]

# ---------------------------------------------------------------------------
# Harness-wrapped tool lists (auto-truncated output)
# Original lists above are preserved for backward compatibility.
# ---------------------------------------------------------------------------

def _wrap_tools(tools: list) -> list:
    """Apply harness tool-output truncation to a list of tools."""
    from app.harness.tool_output import make_truncating_wrapper
    return [make_truncating_wrapper(t) for t in tools]


FUNDAMENTAL_TOOLS_WRAPPED = _wrap_tools(FUNDAMENTAL_TOOLS)
SENTIMENT_TOOLS_WRAPPED = _wrap_tools(SENTIMENT_TOOLS)


__all__ = [
    "ALL_TOOLS",
    "FUNDAMENTAL_TOOLS",
    "SENTIMENT_TOOLS",
    "FUNDAMENTAL_TOOLS_WRAPPED",
    "SENTIMENT_TOOLS_WRAPPED",
    "MARKET_TOOLS",
    "get_financial_statements",
    "get_key_metrics",
    "get_company_profile",
    "get_company_news",
    "get_peer_comparison",
    "get_price_history",
    "get_risk_metrics",
    "get_catalysts",
    "get_strong_stocks",
    "get_market_overview",
    "get_watchlist",
    "add_to_watchlist",
    "remove_from_watchlist",
    "clear_watchlist",
    "create_task",
    "list_tasks",
    "delete_task",
    "list_memories",
    "delete_memory",
    "clear_memories",
    "resolve_symbol",
    "get_technical_analysis",
    "get_monitoring_alerts",
    "get_policy_events",
    "web_search",
]
