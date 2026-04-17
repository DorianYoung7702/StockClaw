"""Sina Finance (新浪财经) data provider (skeleton).

Free real-time quotes for A-share, HK, and US stocks.
No API key required.

Covers: market.
"""

from __future__ import annotations

from typing import Any, Literal

from app.providers.base import FinancialDataProvider


class SinaFinanceProvider(FinancialDataProvider):
    provider_name = "sina_finance"

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("SinaFinanceProvider.get_company_profile not yet implemented")

    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("SinaFinanceProvider does not support financial statements")

    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("SinaFinanceProvider does not support key metrics")

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        raise NotImplementedError("SinaFinanceProvider does not support news")
