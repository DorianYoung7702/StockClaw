"""yfinance-backed financial data provider."""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from app.providers.base import FinancialDataProvider

logger = logging.getLogger(__name__)


def _safe(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


class YFinanceProvider(FinancialDataProvider):
    provider_name = "yfinance"

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        from app.providers.ticker_cache import get_yf_info

        try:
            info = get_yf_info(symbol)
            return {
                "symbol": symbol,
                "name": info.get("longName") or info.get("shortName", ""),
                "industry": info.get("industry", ""),
                "sector": info.get("sector", ""),
                "market_cap": info.get("marketCap"),
                "currency": info.get("currency", "USD"),
                "exchange": info.get("exchange", ""),
                "description": info.get("longBusinessSummary", ""),
                "website": info.get("website", ""),
                "employees": info.get("fullTimeEmployees"),
                "country": info.get("country", ""),
            }
        except Exception as exc:
            logger.warning("yfinance profile failed for %s: %s", symbol, exc)
            return {}

    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        from app.providers.ticker_cache import get_yf_statement

        attr_map = {
            ("income", "annual"): "income_stmt",
            ("income", "quarter"): "quarterly_income_stmt",
            ("balance", "annual"): "balance_sheet",
            ("balance", "quarter"): "quarterly_balance_sheet",
            ("cash", "annual"): "cashflow",
            ("cash", "quarter"): "quarterly_cashflow",
        }
        attr = attr_map.get((statement_type, period))
        if attr is None:
            return []
        try:
            df = get_yf_statement(symbol, attr)
            if df is None or df.empty:
                return []
            df = df.T.reset_index()
            df.rename(columns={"index": "period"}, inplace=True)
            records = df.head(limit).to_dict(orient="records")
            for r in records:
                for k, v in list(r.items()):
                    if hasattr(v, "isoformat"):
                        r[k] = v.isoformat()
                    elif isinstance(v, float) and v != v:
                        r[k] = None
            return records
        except Exception as exc:
            logger.warning("yfinance %s failed for %s: %s", statement_type, symbol, exc)
            return []

    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        from app.providers.ticker_cache import get_yf_info

        try:
            info = get_yf_info(symbol)
            return {
                "pe_ratio": _safe(info.get("trailingPE")),
                "forward_pe": _safe(info.get("forwardPE")),
                "pb_ratio": _safe(info.get("priceToBook")),
                "ps_ratio": _safe(info.get("priceToSalesTrailing12Months")),
                "peg_ratio": _safe(info.get("pegRatio")),
                "ev_to_ebitda": _safe(info.get("enterpriseToEbitda")),
                "dividend_yield": _safe(info.get("dividendYield")),
                "roe": _safe(info.get("returnOnEquity")),
                "roa": _safe(info.get("returnOnAssets")),
                "debt_to_equity": _safe(info.get("debtToEquity")),
                "current_ratio": _safe(info.get("currentRatio")),
                "quick_ratio": _safe(info.get("quickRatio")),
                "gross_margin": _safe(info.get("grossMargins")),
                "operating_margin": _safe(info.get("operatingMargins")),
                "net_margin": _safe(info.get("profitMargins")),
                "revenue_growth_yoy": _safe(info.get("revenueGrowth")),
                "earnings_growth_yoy": _safe(info.get("earningsGrowth")),
                "beta": _safe(info.get("beta")),
                "market_cap": _safe(info.get("marketCap")),
                "current_price": _safe(info.get("currentPrice") or info.get("regularMarketPrice")),
            }
        except Exception as exc:
            logger.warning("yfinance metrics failed for %s: %s", symbol, exc)
            return {}

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        from app.providers.ticker_cache import get_yf_news

        try:
            news = get_yf_news(symbol)
            items = []
            for n in news[:limit]:
                items.append({
                    "title": n.get("title", ""),
                    "url": n.get("link", ""),
                    "source": n.get("publisher", ""),
                    "published": n.get("providerPublishTime", ""),
                    "summary": "",
                })
            return items
        except Exception as exc:
            logger.warning("yfinance news failed for %s: %s", symbol, exc)
            return []
