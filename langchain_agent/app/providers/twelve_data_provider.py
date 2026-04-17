"""Twelve Data provider (skeleton).

Free tier: 800 requests/day, 8 per minute.
Sign up: https://twelvedata.com/

Covers: fundamental, market (built-in technical indicators).
"""

from __future__ import annotations

from typing import Any, Literal

from app.providers.base import FinancialDataProvider


class TwelveDataProvider(FinancialDataProvider):
    provider_name = "twelve_data"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("TwelveDataProvider.get_company_profile not yet implemented")

    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("TwelveDataProvider.get_financial_statement not yet implemented")

    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("TwelveDataProvider.get_key_metrics not yet implemented")

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        raise NotImplementedError("TwelveDataProvider.get_company_news not yet implemented")
