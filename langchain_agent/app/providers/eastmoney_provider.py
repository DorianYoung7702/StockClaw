"""EastMoney (东方财富) data provider — free, no API key required.

Excellent coverage for HK and A-share stocks. Uses public datacenter APIs.
Falls back gracefully for US stocks (limited coverage).
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

import httpx

from app.providers.base import FinancialDataProvider

logger = logging.getLogger(__name__)

_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
_DATA_URL = "https://datacenter.eastmoney.com/securities/api/data/get"

# EastMoney secid prefix by market
_MARKET_PREFIX = {
    "HK": "116",   # Hong Kong
    "SH": "1",     # Shanghai
    "SZ": "0",     # Shenzhen
}


def _is_hk_cn(symbol: str) -> bool:
    """Return True if the symbol is HK or A-share (supported by EastMoney datacenter)."""
    upper = symbol.upper()
    return any(upper.endswith(f".{m}") for m in ("HK", "SH", "SZ"))


def _safe(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _to_em_code(symbol: str) -> tuple[str, str]:
    """Convert ticker like '3317.HK' → ('03317', '03317.HK', '116.03317').

    Returns (em_code_for_filter, secid_for_quote).
    """
    parts = symbol.upper().replace(" ", "").split(".")
    code = parts[0]
    market = parts[1] if len(parts) > 1 else ""

    if market == "HK":
        code = code.zfill(5)  # pad to 5 digits
        secid = f"116.{code}"
        em_filter_code = f"{code}.HK"
    elif market == "SH":
        secid = f"1.{code}"
        em_filter_code = f"{code}.SH"
    elif market == "SZ":
        secid = f"0.{code}"
        em_filter_code = f"{code}.SZ"
    else:
        # US stocks — try secid 105 (NASDAQ) or 106 (NYSE)
        secid = f"105.{code}"
        em_filter_code = f"{code}.O"  # NASDAQ
    return em_filter_code, secid


def _fetch_datacenter(report_type: str, em_code: str, limit: int = 4) -> list[dict]:
    """Fetch from EastMoney datacenter API."""
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(_DATA_URL, params={
                "type": report_type,
                "sty": "ALL",
                "filter": f'(SECUCODE="{em_code}")',
                "p": "1",
                "ps": str(limit),
                "sr": "-1",
                "st": "REPORT_DATE",
                "source": "SECURITIES",
                "client": "PC",
            })
            r.raise_for_status()
            d = r.json()
            result = d.get("result")
            if result and result.get("data"):
                return result["data"]
    except Exception as exc:
        logger.warning("EastMoney datacenter %s failed for %s: %s", report_type, em_code, exc)
    return []


class EastMoneyProvider(FinancialDataProvider):
    """Free financial data from EastMoney (东方财富).

    Best for HK and A-share stocks. No API key required.
    """
    provider_name = "eastmoney"

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=15.0, follow_redirects=True)

    def _quote(self, secid: str) -> dict:
        """Fetch real-time quote data."""
        try:
            r = self._client.get(_QUOTE_URL, params={
                "secid": secid,
                "fields": (
                    "f57,f58,f43,f170,f44,f45,f46,f47,f48,f49,f50,f51,f52,f55,"
                    "f62,f92,f116,f117,f162,f167,f173,f183,f184,f185,f186,f187,f188"
                ),
            })
            r.raise_for_status()
            return r.json().get("data", {}) or {}
        except Exception as exc:
            logger.warning("EastMoney quote failed for %s: %s", secid, exc)
            return {}

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        if not _is_hk_cn(symbol):
            return {}  # let yfinance handle US stocks
        em_code, secid = _to_em_code(symbol)
        quote = self._quote(secid)

        # Try datacenter for detailed profile
        indicators = _fetch_datacenter("RPT_HKF10_FN_MAININDICATOR", em_code, 1)
        ind = indicators[0] if indicators else {}

        name = quote.get("f58") or ind.get("SECURITY_NAME_ABBR", "")
        return {
            "symbol": symbol,
            "name": name,
            "industry": ind.get("ORG_TYPE", ""),
            "sector": "",
            "market_cap": _safe(quote.get("f116")),
            "currency": ind.get("CURRENCY", "HKD"),
            "exchange": em_code.split(".")[-1] if "." in em_code else "",
            "description": "",
            "website": "",
            "employees": None,
            "country": "HK" if ".HK" in em_code else "CN",
            "total_equity": _safe(ind.get("TOTAL_PARENT_EQUITY")),
            "total_assets": _safe(ind.get("TOTAL_ASSETS")),
            "total_liabilities": _safe(ind.get("TOTAL_LIABILITIES")),
        }

    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        if not _is_hk_cn(symbol):
            return {}  # let yfinance handle US stocks
        em_code, secid = _to_em_code(symbol)
        quote = self._quote(secid)
        indicators = _fetch_datacenter("RPT_HKF10_FN_MAININDICATOR", em_code, 1)
        ind = indicators[0] if indicators else {}

        # Quote field mapping:
        # f43=current_price(*10000 for HK), f116=total_market_cap, f117=HK_market_cap
        # f92=debt_asset_ratio, f167=PE(dynamic), f170=change_pct
        price_raw = _safe(quote.get("f43"))
        # HK quotes are in cents (price * 10000), convert
        current_price = price_raw / 10000 if price_raw and price_raw > 1000 else price_raw

        return {
            "pe_ratio": _safe(ind.get("PE_TTM")),
            "pb_ratio": _safe(ind.get("PB_TTM")),
            "roe": _safe(ind.get("ROE_AVG")),
            "roa": _safe(ind.get("ROA")),
            "gross_margin": _safe(ind.get("GROSS_PROFIT_RATIO")),
            "net_margin": _safe(ind.get("NET_PROFIT_RATIO")),
            "debt_to_equity": _safe(ind.get("DEBT_ASSET_RATIO")),
            "current_ratio": _safe(ind.get("CURRENT_RATIO")),
            "revenue_growth_yoy": _safe(ind.get("OPERATE_INCOME_YOY")),
            "earnings_growth_yoy": _safe(ind.get("HOLDER_PROFIT_YOY")),
            "eps": _safe(ind.get("BASIC_EPS")),
            "eps_ttm": _safe(ind.get("EPS_TTM")),
            "bps": _safe(ind.get("BPS")),
            "roic": _safe(ind.get("ROIC_YEARLY")),
            "equity_multiplier": _safe(ind.get("EQUITY_MULTIPLIER")),
            "market_cap": _safe(quote.get("f116") or ind.get("TOTAL_MARKET_CAP")),
            "current_price": current_price,
            "total_assets": _safe(ind.get("TOTAL_ASSETS")),
            "total_liabilities": _safe(ind.get("TOTAL_LIABILITIES")),
            "operate_income": _safe(ind.get("OPERATE_INCOME")),
            "gross_profit": _safe(ind.get("GROSS_PROFIT")),
            "net_profit": _safe(ind.get("HOLDER_PROFIT")),
        }

    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        if not _is_hk_cn(symbol):
            return []  # let yfinance handle US stocks
        em_code, _ = _to_em_code(symbol)

        # HK vs A-share use different report type prefixes
        if symbol.upper().endswith(".HK"):
            prefix = "RPT_HKF10_FN"
        else:
            prefix = "RPT_F10_FINANCE"
        type_map = {
            "income": f"{prefix}_INCOME",
            "balance": f"{prefix}_BALANCE",
            "cash": f"{prefix}_CASHFLOW",
        }
        report_type = type_map.get(statement_type)
        if not report_type:
            return []

        raw = _fetch_datacenter(report_type, em_code, limit * 5)
        if not raw:
            return []

        # Group by REPORT_DATE, filter by period
        from collections import defaultdict
        grouped: dict[str, dict[str, Any]] = defaultdict(dict)
        for item in raw:
            date = item.get("REPORT_DATE", "")
            report = item.get("REPORT_TYPE", "")
            # Filter: 年报 for annual, 中报/季报 for quarter
            if period == "annual" and "年报" not in report:
                continue
            if period == "quarter" and "年报" in report:
                continue
            name = item.get("ITEM_NAME", "")
            amount = item.get("AMOUNT")
            yoy = item.get("YOY_RATIO")
            grouped[date][name] = amount
            if yoy is not None:
                grouped[date][f"{name}_YOY"] = yoy
            grouped[date]["period"] = date[:10]
            grouped[date]["report_type"] = report
            grouped[date]["currency"] = item.get("CURRENCY", "")

        records = list(grouped.values())
        records.sort(key=lambda x: x.get("period", ""), reverse=True)
        return records[:limit]

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        # EastMoney news requires different API; return empty and let
        # sentiment node's web_search + yfinance handle news
        return []
