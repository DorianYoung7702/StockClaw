"""Mock provider returning fixed test data — useful for tests and demos."""

from __future__ import annotations

from typing import Any, Literal

from app.providers.base import FinancialDataProvider

_PROFILES: dict[str, dict[str, Any]] = {
    "AAPL": {
        "symbol": "AAPL", "name": "Apple Inc.", "industry": "Consumer Electronics",
        "sector": "Technology", "market_cap": 3_500_000_000_000, "currency": "USD",
        "exchange": "NASDAQ", "country": "US",
        "description": "Apple designs, manufactures, and markets smartphones, tablets, and computers.",
    },
    "NVDA": {
        "symbol": "NVDA", "name": "NVIDIA Corporation", "industry": "Semiconductors",
        "sector": "Technology", "market_cap": 3_200_000_000_000, "currency": "USD",
        "exchange": "NASDAQ", "country": "US",
        "description": "NVIDIA designs GPUs for gaming, data centers, and AI.",
    },
    "AMD": {
        "symbol": "AMD", "name": "Advanced Micro Devices", "industry": "Semiconductors",
        "sector": "Technology", "market_cap": 220_000_000_000, "currency": "USD",
        "exchange": "NASDAQ", "country": "US",
        "description": "AMD designs CPUs and GPUs for computing and graphics.",
    },
}

_METRICS: dict[str, dict[str, Any]] = {
    "AAPL": {
        "pe_ratio": 32.0, "pb_ratio": 48.0, "ps_ratio": 8.5, "ev_to_ebitda": 26.0,
        "roe": 1.47, "roa": 0.28, "gross_margin": 0.45, "operating_margin": 0.30,
        "net_margin": 0.25, "revenue_growth_yoy": 0.08, "earnings_growth_yoy": 0.12,
        "debt_to_equity": 1.8, "current_ratio": 1.0, "beta": 1.2, "current_price": 195.0,
    },
    "NVDA": {
        "pe_ratio": 65.0, "pb_ratio": 55.0, "ps_ratio": 35.0, "ev_to_ebitda": 50.0,
        "roe": 1.15, "roa": 0.55, "gross_margin": 0.73, "operating_margin": 0.54,
        "net_margin": 0.49, "revenue_growth_yoy": 1.22, "earnings_growth_yoy": 5.81,
        "debt_to_equity": 0.41, "current_ratio": 4.17, "beta": 1.65, "current_price": 135.0,
    },
    "AMD": {
        "pe_ratio": 120.0, "pb_ratio": 4.5, "ps_ratio": 10.0, "ev_to_ebitda": 45.0,
        "roe": 0.04, "roa": 0.02, "gross_margin": 0.50, "operating_margin": 0.05,
        "net_margin": 0.04, "revenue_growth_yoy": 0.10, "earnings_growth_yoy": -0.35,
        "debt_to_equity": 0.04, "current_ratio": 2.5, "beta": 1.55, "current_price": 160.0,
    },
}


class MockProvider(FinancialDataProvider):
    """Returns hardcoded data for AAPL, NVDA, AMD."""
    provider_name = "mock"

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        return _PROFILES.get(symbol.upper(), {"symbol": symbol, "name": symbol, "error": "mock: unknown symbol"})

    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        if symbol.upper() not in _PROFILES:
            return []
        return [
            {"period": f"2024-{statement_type}", "revenue": 400_000_000_000, "net_income": 100_000_000_000},
            {"period": f"2023-{statement_type}", "revenue": 380_000_000_000, "net_income": 95_000_000_000},
        ][:limit]

    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        return _METRICS.get(symbol.upper(), {"error": "mock: unknown symbol"})

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        return [
            {"title": f"{symbol} reports strong quarterly results", "source": "MockNews", "url": "", "summary": "Revenue beat estimates."},
            {"title": f"Analyst upgrades {symbol} to Buy", "source": "MockNews", "url": "", "summary": "Price target raised."},
        ][:limit]
