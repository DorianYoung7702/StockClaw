"""Abstract base class for financial data providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal, Optional


class FinancialDataProvider(ABC):
    """Interface that all data providers must implement."""

    provider_name: str = "unknown"

    @abstractmethod
    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        ...

    @abstractmethod
    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        ...

    @abstractmethod
    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        ...

    # ── Optional: macro data (only for FRED / World Bank / etc.) ──────
    def get_macro_data(self, indicator: str, **kwargs: Any) -> dict[str, Any]:
        """Fetch macroeconomic data. Override in macro-capable providers."""
        raise NotImplementedError(f"{self.provider_name} does not support macro data")
