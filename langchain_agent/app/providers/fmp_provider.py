"""Financial Modeling Prep (FMP) data provider.

Sign up at https://financialmodelingprep.com/ and set FMP_API_KEY in .env.
Plans start at $19/month; provides stable, high-quality financial data with
no rate-limiting issues typical of free sources like yfinance.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

import httpx

from app.providers.base import FinancialDataProvider

logger = logging.getLogger(__name__)

_BASE_URL = "https://financialmodelingprep.com/api/v3"


def _safe(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


class FMPProvider(FinancialDataProvider):
    """Financial Modeling Prep API provider.

    Usage::

        # In .env
        FMP_API_KEY=your_key_here
        FINANCIAL_DATA_PROVIDER=fmp
    """
    provider_name = "fmp"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        if not self._api_key:
            from app.config import get_settings
            self._api_key = get_settings().fmp_api_key
        self._client = httpx.Client(timeout=30.0)

    def _get(self, path: str, params: dict | None = None) -> Any:
        """Make authenticated GET request to FMP API.

        Integrates with CircuitBreaker to prevent cascading failures.
        """
        from app.harness.circuit_breaker import get_breaker

        breaker = get_breaker("fmp")
        if not breaker.allow_request():
            logger.warning("FMP %s: CircuitBreaker OPEN — skipping", path)
            return None

        params = params or {}
        params["apikey"] = self._api_key
        url = f"{_BASE_URL}{path}"
        try:
            resp = self._client.get(url, params=params)
            resp.raise_for_status()
            breaker.record_success()
            return resp.json()
        except Exception as exc:
            breaker.record_failure()
            logger.warning("FMP request failed %s: %s", path, exc)
            return None

    # ---- FinancialDataProvider interface ----

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        data = self._get(f"/profile/{symbol}")
        if not data or not isinstance(data, list) or len(data) == 0:
            return {}
        p = data[0]
        return {
            "symbol": p.get("symbol", symbol),
            "name": p.get("companyName", ""),
            "industry": p.get("industry", ""),
            "sector": p.get("sector", ""),
            "market_cap": p.get("mktCap"),
            "currency": p.get("currency", "USD"),
            "exchange": p.get("exchangeShortName", ""),
            "description": p.get("description", ""),
            "website": p.get("website", ""),
            "employees": p.get("fullTimeEmployees"),
            "country": p.get("country", ""),
            "ceo": p.get("ceo", ""),
            "ipo_date": p.get("ipoDate", ""),
            "current_price": _safe(p.get("price")),
            "beta": _safe(p.get("beta")),
        }

    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        endpoint_map = {
            "income": "/income-statement",
            "balance": "/balance-sheet-statement",
            "cash": "/cash-flow-statement",
        }
        path = f"{endpoint_map[statement_type]}/{symbol}"
        params: dict[str, Any] = {"limit": limit}
        if period == "quarter":
            params["period"] = "quarter"

        data = self._get(path, params)
        if not data or not isinstance(data, list):
            return []

        records = []
        for row in data[:limit]:
            clean: dict[str, Any] = {}
            for k, v in row.items():
                if isinstance(v, float) and v != v:
                    clean[k] = None
                else:
                    clean[k] = v
            records.append(clean)
        return records

    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        # Combine key metrics + ratios for comprehensive data
        metrics = self._get(f"/key-metrics-ttm/{symbol}")
        ratios = self._get(f"/ratios-ttm/{symbol}")

        out: dict[str, Any] = {}

        if metrics and isinstance(metrics, list) and metrics:
            m = metrics[0]
            out.update({
                "pe_ratio": _safe(m.get("peRatioTTM")),
                "pb_ratio": _safe(m.get("pbRatioTTM")),
                "ps_ratio": _safe(m.get("priceToSalesRatioTTM")),
                "peg_ratio": _safe(m.get("pegRatioTTM")),
                "ev_to_ebitda": _safe(m.get("enterpriseValueOverEBITDATTM")),
                "dividend_yield": _safe(m.get("dividendYieldTTM")),
                "market_cap": _safe(m.get("marketCapTTM")),
                "debt_to_equity": _safe(m.get("debtToEquityTTM")),
                "current_ratio": _safe(m.get("currentRatioTTM")),
            })

        if ratios and isinstance(ratios, list) and ratios:
            r = ratios[0]
            out.update({
                "roe": _safe(r.get("returnOnEquityTTM")),
                "roa": _safe(r.get("returnOnAssetsTTM")),
                "gross_margin": _safe(r.get("grossProfitMarginTTM")),
                "operating_margin": _safe(r.get("operatingProfitMarginTTM")),
                "net_margin": _safe(r.get("netProfitMarginTTM")),
                "quick_ratio": _safe(r.get("quickRatioTTM")),
            })

        # Growth metrics
        growth = self._get(f"/financial-growth/{symbol}", {"limit": 1})
        if growth and isinstance(growth, list) and growth:
            g = growth[0]
            out.update({
                "revenue_growth_yoy": _safe(g.get("revenueGrowth")),
                "earnings_growth_yoy": _safe(g.get("netIncomeGrowth")),
            })

        # Current price from quote
        quote = self._get(f"/quote-short/{symbol}")
        if quote and isinstance(quote, list) and quote:
            out["current_price"] = _safe(quote[0].get("price"))

        return out

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        data = self._get("/stock_news", {"tickers": symbol, "limit": limit})
        if not data or not isinstance(data, list):
            return []
        items = []
        for n in data[:limit]:
            items.append({
                "title": n.get("title", ""),
                "url": n.get("url", ""),
                "source": n.get("site", ""),
                "published": n.get("publishedDate", ""),
                "summary": n.get("text", "")[:300] if n.get("text") else "",
            })
        return items
