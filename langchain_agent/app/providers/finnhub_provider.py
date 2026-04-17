"""Finnhub provider.

Primarily news-focused in current Atlas integration.
Other fundamental interfaces intentionally return empty payloads.
"""

from __future__ import annotations

from typing import Any, Literal

from app.providers.base import FinancialDataProvider
from app.providers.finnhub_news import fetch_finnhub_news


class FinnhubProvider(FinancialDataProvider):
    provider_name = "finnhub"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        del symbol
        return {}

    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        del symbol, statement_type, period, limit
        return []

    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        del symbol
        return {}

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        return fetch_finnhub_news(symbol, limit=limit, api_key=self._api_key or None)
