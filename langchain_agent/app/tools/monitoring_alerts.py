"""Tool for scanning the monitoring pool for low-volatility / breakout alerts.

Wraps StockAnalyzer.analyze_monitoring_pool from the monitor/ module and
returns structured alert data for the chat agent.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.config import get_settings

logger = logging.getLogger(__name__)


class MonitoringAlertsInput(BaseModel):
    market_type: Literal["us_stock", "etf", "hk_stock"] = Field(
        default="us_stock",
        description="Market type: us_stock, etf, or hk_stock",
    )
    timeframe: Literal["1d", "4h"] = Field(
        default="1d",
        description="Timeframe to scan: 1d (daily) or 4h (4-hour)",
    )


def _ensure_monitor_path() -> None:
    root = str(get_settings().monitor_module_root)
    if root not in sys.path:
        sys.path.insert(0, root)


@tool("get_monitoring_alerts", args_schema=MonitoringAlertsInput)
def get_monitoring_alerts(
    market_type: str = "us_stock",
    timeframe: str = "1d",
) -> str:
    """Scan the strong-stock monitoring pool for low-volatility and breakout alerts.

    Analyzes each high-performance stock in the cached monitoring pool using
    RSI, moving-average convergence, and ATR-based breakout detection.
    Returns a list of active alerts with signal type, RSI, and symbol info.
    This is a heavier operation that may take a while.
    """
    _ensure_monitor_path()
    try:
        from config import Config as MonitorConfig
        from config import MarketType as MonitorMarketType
        from stock_analyzer import StockAnalyzer

        mt = MonitorMarketType(market_type)
        cfg = MonitorConfig()
        cfg.cache_dir = str(get_settings().monitor_module_root / "cache")

        analyzer = StockAnalyzer(cfg)

        alerts, analysis_results = analyzer.analyze_monitoring_pool(timeframe, mt)

        alert_items = []
        for alert in alerts:
            alert_items.append({
                "symbol": alert.symbol,
                "name": alert.name,
                "timeframe": alert.timeframe,
                "alert_type": alert.alert_type,
                "rsi": round(alert.rsi_value, 1),
                "message": alert.format_message(),
            })

        analysis_items = []
        for sym, tf_data in analysis_results.items():
            for tf, result in tf_data.items():
                analysis_items.append({
                    "symbol": sym,
                    "timeframe": tf,
                    "rsi": round(result["rsi"], 1) if result.get("rsi") else None,
                    "low_volatility": result.get("is_low_volatility", False),
                    "breakout": result.get("is_breakout", False),
                    "data_points": result.get("data_points", 0),
                })

        if not alert_items and not analysis_items:
            return json.dumps({
                "message": f"监控池（{market_type}）暂无数据或尚未构建。请先运行 build_monitoring_pool。",
                "alerts": [],
                "scanned": [],
            })

        return json.dumps(
            {
                "market_type": market_type,
                "timeframe": timeframe,
                "alert_count": len(alert_items),
                "scanned_count": len(analysis_items),
                "alerts": alert_items,
                "scanned": analysis_items,
            },
            default=str,
            ensure_ascii=False,
        )

    except Exception as exc:
        logger.warning("get_monitoring_alerts failed: %s", exc)
        return json.dumps({"error": f"Monitoring alert scan failed: {exc}"})
