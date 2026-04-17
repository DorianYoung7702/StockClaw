"""OpenBB-backed financial data provider."""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

from app.providers.base import FinancialDataProvider

logger = logging.getLogger(__name__)


class OpenBBProvider(FinancialDataProvider):
    provider_name = "openbb"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        if api_key:
            # OpenBB SDK auth envs (different versions use different names)
            os.environ["OPENBB_TOKEN"] = api_key
            os.environ["OPENBB_PAT"] = api_key

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        try:
            from openbb import obb

            result = obb.equity.profile(symbol=symbol, provider="yfinance")
            df = result.to_dataframe()
            if df.empty:
                return {}
            row = df.iloc[0].to_dict()
            for k, v in list(row.items()):
                if isinstance(v, float) and v != v:
                    row[k] = None
                elif hasattr(v, "isoformat"):
                    row[k] = v.isoformat()
            return row
        except Exception as exc:
            logger.debug("OpenBB profile failed for %s: %s", symbol, exc)
            return {}

    def get_financial_statement(
        self,
        symbol: str,
        statement_type: Literal["income", "balance", "cash"],
        period: Literal["annual", "quarter"] = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        try:
            from openbb import obb

            fetcher = {
                "income": obb.equity.fundamental.income,
                "balance": obb.equity.fundamental.balance,
                "cash": obb.equity.fundamental.cash,
            }[statement_type]

            result = fetcher(symbol=symbol, period=period, limit=limit, provider="yfinance")
            df = result.to_dataframe()
            if df.empty:
                return []
            records = df.reset_index().to_dict(orient="records")
            for r in records:
                for k, v in list(r.items()):
                    if hasattr(v, "isoformat"):
                        r[k] = v.isoformat()
                    elif isinstance(v, float) and (v != v):
                        r[k] = None
            return records
        except Exception as exc:
            logger.debug("OpenBB %s failed for %s: %s", statement_type, symbol, exc)
            return []

    def get_key_metrics(self, symbol: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        try:
            from openbb import obb

            metrics = obb.equity.fundamental.metrics(symbol=symbol, provider="yfinance")
            df = metrics.to_dataframe()
            if not df.empty:
                out.update(df.iloc[0].to_dict())
        except Exception as exc:
            logger.debug("OpenBB metrics failed for %s: %s", symbol, exc)

        try:
            from openbb import obb

            ratios = obb.equity.fundamental.ratios(symbol=symbol, provider="yfinance")
            df = ratios.to_dataframe()
            if not df.empty:
                out.update(df.iloc[0].to_dict())
        except Exception as exc:
            logger.debug("OpenBB ratios failed for %s: %s", symbol, exc)

        return out

    def get_company_news(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        try:
            from openbb import obb

            result = obb.news.company(symbol=symbol, limit=limit, provider="yfinance")
            df = result.to_dataframe()
            if df.empty:
                return []
            records = df.reset_index().to_dict(orient="records")
            cleaned = []
            for r in records:
                item = {
                    "title": str(r.get("title", "")),
                    "url": str(r.get("url") or r.get("link", "")),
                    "source": str(r.get("source", "")),
                    "summary": str(r.get("text") or r.get("summary", "")),
                }
                pub = r.get("date") or r.get("published")
                if pub is not None:
                    item["published"] = pub.isoformat() if hasattr(pub, "isoformat") else str(pub)
                cleaned.append(item)
            return cleaned[:limit]
        except Exception as exc:
            logger.debug("OpenBB news failed for %s: %s", symbol, exc)
            return []
