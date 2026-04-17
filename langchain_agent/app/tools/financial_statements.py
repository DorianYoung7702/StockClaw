"""Tools for fetching financial statements (income, balance sheet, cash flow) via OpenBB."""

from __future__ import annotations

import json
import logging
from typing import Literal, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Quick check: is OpenBB actually usable? (import alone succeeds but
# obb.equity.fundamental may fail on Python 3.14 due to missing submodules)
try:
    from openbb import obb as _obb_check  # noqa: F401
    _ = _obb_check.equity.fundamental  # trigger the deeper import
    _OPENBB_AVAILABLE = True
except Exception:
    _OPENBB_AVAILABLE = False
    logger.info("OpenBB not usable — financial_statements will use yfinance fallback")


class FinancialStatementsInput(BaseModel):
    symbol: str = Field(description="Ticker symbol, e.g. AAPL, MSFT, 00700.HK")
    statement_type: Literal["income", "balance", "cash"] = Field(
        default="income",
        description="Type of financial statement: income, balance, or cash",
    )
    period: Literal["annual", "quarter"] = Field(
        default="annual",
        description="Reporting period: annual or quarter",
    )
    limit: int = Field(default=4, description="Number of periods to return")


def _safe_float(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fetch_via_openbb(symbol: str, stmt: str, period: str, limit: int) -> list[dict]:
    if not _OPENBB_AVAILABLE:
        return []
    try:
        from openbb import obb

        fetcher = {
            "income": obb.equity.fundamental.income,
            "balance": obb.equity.fundamental.balance,
            "cash": obb.equity.fundamental.cash,
        }[stmt]

        result = fetcher(symbol=symbol, period=period, limit=limit, provider="yfinance")
        df = result.to_dataframe()
        if df.empty:
            return []
        records = df.reset_index().to_dict(orient="records")
        for r in records:
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
                elif isinstance(v, float) and (v != v):  # NaN
                    r[k] = None
        return records
    except Exception as exc:
        logger.warning("OpenBB %s fetch failed for %s: %s", stmt, symbol, exc)
        return []


def _fetch_via_yfinance(symbol: str, stmt: str, period: str) -> list[dict]:
    """Fallback to raw yfinance when OpenBB fails."""
    from app.providers.ticker_cache import get_yf_statement

    attr_map = {
        ("income", "annual"): "income_stmt",
        ("income", "quarter"): "quarterly_income_stmt",
        ("balance", "annual"): "balance_sheet",
        ("balance", "quarter"): "quarterly_balance_sheet",
        ("cash", "annual"): "cashflow",
        ("cash", "quarter"): "quarterly_cashflow",
    }
    attr = attr_map.get((stmt, period))
    if attr is None:
        return []
    try:
        df = get_yf_statement(symbol, attr)
        if df is None or df.empty:
            return []
        df = df.T.reset_index()
        df.rename(columns={"index": "period"}, inplace=True)
        records = df.head(8).to_dict(orient="records")
        for r in records:
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
                elif isinstance(v, float) and (v != v):
                    r[k] = None
        return records
    except Exception as exc:
        logger.warning("yfinance %s fallback failed for %s: %s", stmt, symbol, exc)
        return []


def _fetch_via_configured_provider(symbol: str, stmt: str, period: str, limit: int) -> list[dict]:
    """Try providers in user-configured priority order for 'fundamental' category."""
    from app.context import current_user_id
    from app.providers.registry import get_prioritized_providers

    user_id = current_user_id.get("default")
    providers = get_prioritized_providers(user_id, "fundamental")

    for provider in providers:
        try:
            result = provider.get_financial_statement(symbol, stmt, period, limit)
            if result:
                logger.debug("statements:%s/%s served by %s", symbol, stmt, provider.provider_name)
                return result
        except Exception as exc:
            logger.debug("Provider %s %s failed for %s: %s", provider.provider_name, stmt, symbol, exc)
    return []


@tool("get_financial_statements", args_schema=FinancialStatementsInput)
def get_financial_statements(
    symbol: str,
    statement_type: str = "income",
    period: str = "annual",
    limit: int = 4,
) -> str:
    """Fetch financial statements (income / balance sheet / cash flow) for a company.

    Returns a JSON array of statement rows ordered from newest to oldest.
    Each row contains standard accounting line items for the requested statement type.
    """
    # Try configured provider first (e.g. FMP)
    records = _fetch_via_configured_provider(symbol, statement_type, period, limit)
    if not records:
        records = _fetch_via_openbb(symbol, statement_type, period, limit)
    if not records:
        records = _fetch_via_yfinance(symbol, statement_type, period)
    if not records:
        return json.dumps({"error": f"No {statement_type} data found for {symbol}"})
    return json.dumps(records[:limit], default=str, ensure_ascii=False)
