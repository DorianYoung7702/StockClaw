"""SEC EDGAR data provider (skeleton).

US SEC filings (10-K, 10-Q, etc.).  Free, unlimited.
Docs: https://www.sec.gov/edgar/

Covers: fundamental (filings text).
"""

from __future__ import annotations

from typing import Any, Literal

from app.providers.base import FinancialDataProvider


class SECEdgarProvider(FinancialDataProvider):
    provider_name = "sec_edgar"

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("SECEdgarProvider.get_company_profile not yet implemented")

    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("SECEdgarProvider.get_financial_statement not yet implemented")

    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("SECEdgarProvider.get_key_metrics not yet implemented")

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        raise NotImplementedError("SECEdgarProvider does not support news")
