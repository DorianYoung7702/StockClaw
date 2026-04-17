"""NewsAPI data provider (skeleton).

Global news aggregation from 100+ sources.
Free tier: 100 requests/day.
Sign up: https://newsapi.org/

Covers: news.
"""

from __future__ import annotations

from typing import Any, Literal

from app.providers.base import FinancialDataProvider


class NewsAPIProvider(FinancialDataProvider):
    provider_name = "newsapi"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("NewsAPIProvider does not support company profiles")

    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("NewsAPIProvider does not support financial statements")

    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("NewsAPIProvider does not support key metrics")

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        raise NotImplementedError("NewsAPIProvider.get_company_news not yet implemented")
