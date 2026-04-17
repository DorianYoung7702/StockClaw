"""World Bank data provider (skeleton).

Global economic indicators for 200+ countries.  Free, unlimited.
Docs: https://data.worldbank.org/

Covers: macro.
"""

from __future__ import annotations

from typing import Any, Literal

from app.providers.base import FinancialDataProvider


class WorldBankProvider(FinancialDataProvider):
    provider_name = "world_bank"

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("WorldBankProvider does not support company profiles")

    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("WorldBankProvider does not support financial statements")

    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("WorldBankProvider does not support key metrics")

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        raise NotImplementedError("WorldBankProvider does not support news")

    def get_macro_data(self, indicator: str, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("WorldBankProvider.get_macro_data not yet implemented")
