"""AKShare data provider (skeleton).

Free A-share data aggregator, no API key required.
Docs: https://akshare.akfamily.xyz/

Covers: fundamental, market.
"""

from __future__ import annotations

from typing import Any, Literal

from app.providers.base import FinancialDataProvider


class AKShareProvider(FinancialDataProvider):
    provider_name = "akshare"

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("AKShareProvider.get_company_profile not yet implemented")

    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("AKShareProvider.get_financial_statement not yet implemented")

    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("AKShareProvider.get_key_metrics not yet implemented")

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        raise NotImplementedError("AKShareProvider.get_company_news not yet implemented")
