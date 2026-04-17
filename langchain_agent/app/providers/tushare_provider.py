"""Tushare data provider (skeleton).

A-share / HK stock data.  Free registration with token.
Sign up: https://tushare.pro/

Covers: fundamental, market.
"""

from __future__ import annotations

from typing import Any, Literal

from app.providers.base import FinancialDataProvider


class TushareProvider(FinancialDataProvider):
    provider_name = "tushare"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("TushareProvider.get_company_profile not yet implemented")

    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("TushareProvider.get_financial_statement not yet implemented")

    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("TushareProvider.get_key_metrics not yet implemented")

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        raise NotImplementedError("TushareProvider.get_company_news not yet implemented")
