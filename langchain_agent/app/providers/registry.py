"""Provider registry — returns the configured provider instance.

Supports all 17 data sources with lazy imports.  Use ``get_provider()`` for
a single provider instance, or ``get_prioritized_providers()`` to get an
ordered list based on the user's data-source configuration.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.providers.base import FinancialDataProvider

logger = logging.getLogger(__name__)

# Cache per (name, api_key) so the same provider+key combo is reused.
_cache: dict[tuple[str, str], FinancialDataProvider] = {}


def get_provider(name: str = "yfinance", api_key: Optional[str] = None) -> FinancialDataProvider:
    """Return a provider instance by name.

    Supported (implemented): fmp, eastmoney, openbb, yfinance, finnhub, mock.
    Skeleton (not yet implemented): alpha_vantage, polygon, twelve_data, tiingo,
    tushare, akshare, newsapi, sec_edgar, fred, world_bank, sina_finance, xueqiu.
    """
    cache_key = (name, api_key or "")
    if cache_key in _cache:
        return _cache[cache_key]

    provider = _create_provider(name, api_key)
    _cache[cache_key] = provider
    return provider


def _create_provider(name: str, api_key: Optional[str] = None) -> FinancialDataProvider:
    """Lazy-import and instantiate a provider by name."""
    # ── Existing (implemented) ──────────────────────────────────────
    if name == "fmp":
        from app.providers.fmp_provider import FMPProvider
        return FMPProvider(api_key=api_key or "")
    elif name == "eastmoney":
        from app.providers.eastmoney_provider import EastMoneyProvider
        return EastMoneyProvider()
    elif name == "openbb":
        from app.providers.openbb_provider import OpenBBProvider
        return OpenBBProvider(api_key=api_key or "")
    elif name == "finnhub":
        from app.providers.finnhub_provider import FinnhubProvider
        return FinnhubProvider(api_key=api_key or "")
    elif name == "mock":
        from app.providers.mock_provider import MockProvider
        return MockProvider()
    # ── New skeleton providers ──────────────────────────────────────
    elif name == "alpha_vantage":
        from app.providers.alpha_vantage_provider import AlphaVantageProvider
        return AlphaVantageProvider(api_key=api_key or "")
    elif name == "polygon":
        from app.providers.polygon_provider import PolygonProvider
        return PolygonProvider(api_key=api_key or "")
    elif name == "twelve_data":
        from app.providers.twelve_data_provider import TwelveDataProvider
        return TwelveDataProvider(api_key=api_key or "")
    elif name == "tiingo":
        from app.providers.tiingo_provider import TiingoProvider
        return TiingoProvider(api_key=api_key or "")
    elif name == "tushare":
        from app.providers.tushare_provider import TushareProvider
        return TushareProvider(api_key=api_key or "")
    elif name == "akshare":
        from app.providers.akshare_provider import AKShareProvider
        return AKShareProvider()
    elif name == "newsapi":
        from app.providers.newsapi_provider import NewsAPIProvider
        return NewsAPIProvider(api_key=api_key or "")
    elif name == "sec_edgar":
        from app.providers.sec_edgar_provider import SECEdgarProvider
        return SECEdgarProvider()
    elif name == "fred":
        from app.providers.fred_provider import FREDProvider
        return FREDProvider(api_key=api_key or "")
    elif name == "world_bank":
        from app.providers.world_bank_provider import WorldBankProvider
        return WorldBankProvider()
    elif name == "sina_finance":
        from app.providers.sina_finance_provider import SinaFinanceProvider
        return SinaFinanceProvider()
    elif name == "xueqiu":
        from app.providers.xueqiu_provider import XueqiuProvider
        return XueqiuProvider()
    else:
        from app.providers.yfinance_provider import YFinanceProvider
        return YFinanceProvider()


def get_prioritized_providers(
    user_id: str = "",
    category: str = "fundamental",
) -> list[FinancialDataProvider]:
    """Return provider instances for *category*, sorted by user priority.

    Reads from ``DataSourceConfigStore`` and resolves API keys.
    Skips unimplemented and disabled providers.
    """
    from app.harness.datasource_config import get_datasource_config_store

    store = get_datasource_config_store()
    ordered_names = store.get_provider_priority(user_id, category)

    providers: list[FinancialDataProvider] = []
    for name in ordered_names:
        try:
            api_key = store.get_api_key(user_id, name)
            providers.append(get_provider(name, api_key or None))
        except Exception as exc:
            logger.debug("Failed to load provider '%s': %s", name, exc)
    return providers
