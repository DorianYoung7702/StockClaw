"""FRED (Federal Reserve Economic Data) provider (skeleton).

Free API key.  GDP, CPI, interest rates, employment data.
Sign up: https://fred.stlouisfed.org/docs/api/api_key.html

Covers: macro.
"""

from __future__ import annotations

from typing import Any, Literal

from app.providers.base import FinancialDataProvider


class FREDProvider(FinancialDataProvider):
    provider_name = "fred"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("FREDProvider does not support company profiles")

    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("FREDProvider does not support financial statements")

    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("FREDProvider does not support key metrics")

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        raise NotImplementedError("FREDProvider does not support news")

    def get_macro_data(self, indicator: str, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("FREDProvider.get_macro_data not yet implemented")
