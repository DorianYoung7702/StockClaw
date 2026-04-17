"""Polygon.io data provider (skeleton).

Free tier: 5 requests/minute.  Paid plans for real-time data.
Sign up: https://polygon.io/

Covers: fundamental, news, market (real-time + historical).
"""

from __future__ import annotations

from typing import Any, Literal

from app.providers.base import FinancialDataProvider


class PolygonProvider(FinancialDataProvider):
    provider_name = "polygon"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("PolygonProvider.get_company_profile not yet implemented")

    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("PolygonProvider.get_financial_statement not yet implemented")

    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("PolygonProvider.get_key_metrics not yet implemented")

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        raise NotImplementedError("PolygonProvider.get_company_news not yet implemented")
