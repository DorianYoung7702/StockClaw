"""Xueqiu (雪球) data provider (skeleton).

Community sentiment + market data.  No API key required.
Note: uses public web endpoints, not an official API.

Covers: news, market.
"""

from __future__ import annotations

from typing import Any, Literal

from app.providers.base import FinancialDataProvider


class XueqiuProvider(FinancialDataProvider):
    provider_name = "xueqiu"

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("XueqiuProvider.get_company_profile not yet implemented")

    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("XueqiuProvider does not support financial statements")

    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("XueqiuProvider does not support key metrics")

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        raise NotImplementedError("XueqiuProvider.get_company_news not yet implemented")
