"""Tool bridging the existing openbb/ strong-stock monitoring module."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Literal, Optional

import numpy as np
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.config import get_settings

logger = logging.getLogger(__name__)


class StrongStocksInput(BaseModel):
    market_type: Literal["us_stock", "etf", "hk_stock"] = Field(
        default="us_stock",
        description="Market type: us_stock, etf, or hk_stock",
    )
    top_count: Optional[int] = Field(
        default=None,
        description="Max number of stocks to return (e.g. 10, 20). None = use default.",
    )
    rsi_threshold: Optional[float] = Field(
        default=None,
        description="RSI strength threshold (e.g. 50, 60, 70). Only stocks above this RSI are included.",
    )
    sort_by: Optional[str] = Field(
        default=None,
        description="Sort field: momentum_score, performance_20d, rs_20d, vol_score, or trend_r2",
    )
    min_volume_turnover: Optional[float] = Field(
        default=None,
        description="Minimum 5-day average turnover in raw value (e.g. 600000000 for 6亿). None = use default.",
    )


def _ensure_monitor_path() -> None:
    settings = get_settings()
    root = str(settings.monitor_module_root)
    if root not in sys.path:
        sys.path.insert(0, root)


def _build_strength_reason(item: dict) -> str:
    """Generate a concise rules-based explanation of why a stock is strong."""
    parts: list[str] = []
    ms = item.get("momentum_score", 0)
    rs = item.get("rs_20d", 0)
    vs = item.get("vol_score", 1.0)
    tr = item.get("trend_r2", 0)
    p20 = item.get("performance_20d", 0)

    # Relative strength
    if rs > 15:
        parts.append(f"20日超额收益{rs:+.1f}%，大幅跑赢基准")
    elif rs > 5:
        parts.append(f"20日超额收益{rs:+.1f}%，明显领先大盘")
    elif rs > 0:
        parts.append(f"20日超额收益{rs:+.1f}%，跑赢基准")

    # Volume cooperation
    if vs > 1.5:
        parts.append(f"量价齐升（量比{vs:.2f}x），资金持续流入")
    elif vs > 1.1:
        parts.append(f"成交温和放量（量比{vs:.2f}x）")
    elif vs < 0.7:
        parts.append("缩量上涨，关注持续性")

    # Trend smoothness
    if tr > 0.85:
        parts.append(f"趋势极度平滑（R²={tr:.2f}），走势稳健")
    elif tr > 0.6:
        parts.append(f"趋势较平滑（R²={tr:.2f}）")
    elif tr < 0.3:
        parts.append("走势波动较大，趋势不明确")

    # Overall momentum score label
    if ms > 0.7:
        label = "强势评分极高"
    elif ms > 0.5:
        label = "强势评分较高"
    elif ms > 0.3:
        label = "强势评分中等"
    else:
        label = "强势评分偏低"
    header = f"{label}（{ms:.2f}）"

    if parts:
        return f"{header}：{'；'.join(parts)}"
    return header


def _get_benchmark_symbol(market_type_str: str) -> str:
    benchmarks = {
        "us_stock": "SPY",
        "etf": "SPY",
        "hk_stock": "^HSI",
    }
    return benchmarks.get(market_type_str, "SPY")


def _safe_round(value: Any, digits: int = 4) -> Any:
    if isinstance(value, (int, float, np.integer, np.floating)):
        val = float(value)
        if val != val:
            return None
        return round(val, digits)
    return value


def load_single_strong_stock(ticker: str, market_type: str = "us_stock") -> dict[str, Any]:
    """Compute strong-stock style recent metrics for a single ticker.

    Uses the same core formula as the monitoring pool so the frontend can fetch
    one unloaded card without refreshing the entire market cache.
    """
    _ensure_monitor_path()

    from app.providers.ticker_cache import get_yf_history, get_yf_info
    from utils import format_symbol_name

    symbol = format_symbol_name(ticker)
    bench_symbol = _get_benchmark_symbol(market_type)

    hist = get_yf_history(symbol, period="6mo", interval="1d")
    if hist is None or hist.empty or len(hist) < 21:
        raise ValueError(f"Insufficient price data for {ticker}")

    bench = get_yf_history(bench_symbol, period="6mo", interval="1d")

    close = hist["Close"].astype(float)
    high = hist["High"].astype(float)
    low = hist["Low"].astype(float)
    volume = hist["Volume"].astype(float)

    recent = hist.tail(5)
    hlc3 = (recent["High"].astype(float) + recent["Low"].astype(float) + recent["Close"].astype(float)) / 3
    volume_5d_avg = float((recent["Volume"].astype(float) * hlc3).mean())
    current_price = float(close.iloc[-1])

    def perf(days: int) -> Optional[float]:
        if len(close) <= days:
            return None
        base = float(close.iloc[-days - 1])
        if base == 0:
            return None
        return float((current_price - base) / base * 100)

    benchmark_perf: dict[int, float] = {}
    if bench is not None and not bench.empty and "Close" in bench:
        bench_close = bench["Close"].astype(float)
        for days in (20, 40, 90, 180):
            if len(bench_close) > days:
                base = float(bench_close.iloc[-days - 1])
                if base != 0:
                    benchmark_perf[days] = float((float(bench_close.iloc[-1]) - base) / base * 100)

    performance_20d = perf(20)
    performance_40d = perf(40)
    performance_90d = perf(90)
    performance_180d = perf(180)
    if performance_180d is None and performance_90d is not None:
        performance_180d = performance_90d

    rs_20d = (performance_20d or 0.0) - benchmark_perf.get(20, 0.0)

    vol_score = 1.0
    if len(volume) >= 40:
        vol_recent = float(volume.iloc[-20:].mean())
        vol_prev = float(volume.iloc[-40:-20].mean())
        if vol_prev > 0:
            vol_score = vol_recent / vol_prev

    trend_r2 = 0.0
    if len(close) >= 20:
        closes_20 = close.iloc[-20:].values.astype(float)
        x = np.arange(len(closes_20))
        closes_norm = closes_20 / closes_20[0]
        coeffs = np.polyfit(x, closes_norm, 1)
        y_pred = np.polyval(coeffs, x)
        ss_res = np.sum((closes_norm - y_pred) ** 2)
        ss_tot = np.sum((closes_norm - closes_norm.mean()) ** 2)
        if ss_tot > 0:
            trend_r2 = max(0.0, float(1 - ss_res / ss_tot))

    rs_score = min(max(rs_20d / 50.0, 0.0), 1.0)
    vol_norm = min(max((vol_score - 0.5) / 1.5, 0.0), 1.0)
    momentum_score = rs_score * 0.4 + vol_norm * 0.3 + trend_r2 * 0.3

    info = get_yf_info(symbol)
    display_name = (
        info.get("longName")
        or info.get("shortName")
        or info.get("displayName")
        or ticker
    )

    item = {
        "symbol": ticker,
        "name": display_name,
        "current_price": current_price,
        "performance_20d": performance_20d,
        "performance_40d": performance_40d,
        "performance_90d": performance_90d,
        "performance_180d": performance_180d,
        "rs_20d": rs_20d,
        "vol_score": vol_score,
        "trend_r2": trend_r2,
        "momentum_score": momentum_score,
        "volume_5d_avg": volume_5d_avg,
    }
    item = {k: _safe_round(v) for k, v in item.items()}
    item["symbol"] = ticker
    item["name"] = display_name
    item["reason"] = _build_strength_reason(item)
    return item


def _load_strong_stocks(
    market_type_str: str,
    *,
    top_count: Optional[int] = None,
    rsi_threshold: Optional[float] = None,
    momentum_days: Optional[list[int]] = None,
    top_volume_count: Optional[int] = None,
    sort_by: Optional[str] = None,
    min_volume_turnover: Optional[float] = None,
) -> list[dict]:
    """Load strong stocks from existing monitor/ module with graceful fallback.

    Optional keyword arguments override the corresponding monitor Config defaults.
    """
    _ensure_monitor_path()
    try:
        from config import Config as OBBConfig
        from config import MarketType as OBBMarketType
        from data_loader import DataLoader

        mt = OBBMarketType(market_type_str)
        cfg = OBBConfig()
        cfg.cache_dir = str(get_settings().monitor_module_root / "cache")
        if top_count is not None:
            cfg.top_performers_count = top_count
        if rsi_threshold is not None:
            cfg.rsi_strong_threshold = rsi_threshold
        if momentum_days is not None:
            cfg.performance_periods = momentum_days
        if top_volume_count is not None:
            cfg.top_volume_count = top_volume_count

        loader = DataLoader(cfg)
        df = loader.get_monitoring_pool_data(mt, flag_top_only=True)

        # --- On-demand rebuild logic ---
        # 1) Cache missing entirely → build with default top_n
        # 2) User requested top_volume_count > cached pool size → rebuild with larger top_n
        try:
            from app.providers.monitor_pool_builder import monitor_cache_exists, build_monitor_pool
            need_rebuild = False
            rebuild_top_n = 0  # 0 = use all symbols from CSV

            if df.empty and not monitor_cache_exists(market_type_str):
                # Case 1: no cache at all
                need_rebuild = True
                rebuild_top_n = top_volume_count or 0
                logger.info("strong_stocks: cache missing for %s, building (top_n=%d)...", market_type_str, rebuild_top_n)
            elif top_volume_count is not None and not df.empty:
                # Case 2: user wants more symbols than current pool has
                cached_count = len(df)
                if top_volume_count > cached_count:
                    need_rebuild = True
                    rebuild_top_n = top_volume_count
                    logger.info("strong_stocks: user wants top_volume_count=%d but pool has %d, rebuilding %s...",
                                top_volume_count, cached_count, market_type_str)

            if need_rebuild:
                build_monitor_pool(market_type_str, top_n=rebuild_top_n)
                df = loader.get_monitoring_pool_data(mt, flag_top_only=True)
        except Exception as build_exc:
            logger.warning("strong_stocks: on-demand build failed for %s: %s", market_type_str, build_exc)

        if df.empty:
            return []

        # Apply volume floor per market (user override or default)
        if min_volume_turnover is not None:
            floor = min_volume_turnover
        else:
            vol_floors = {"us_stock": 6e8, "hk_stock": 5e7, "etf": 2e7}
            floor = vol_floors.get(market_type_str, 0)
        if "volume_5d_avg" in df.columns and floor > 0:
            df = df[df["volume_5d_avg"] >= floor]

        # Sort by user-selected field or default
        if sort_by and sort_by in df.columns:
            sort_col = sort_by
        else:
            sort_col = "momentum_score" if "momentum_score" in df.columns else "performance_20d"
        df = df.sort_values(by=sort_col, ascending=False)

        # Limit to top_count per period union (same logic as original)
        tc = cfg.top_performers_count
        items = []
        keep_cols = [
            "symbol", "name", "current_price",
            "performance_20d", "performance_40d", "performance_90d", "performance_180d",
            "rs_20d", "vol_score", "trend_r2", "momentum_score",
            "volume_5d_avg",
        ]
        for _, row in df.head(tc).iterrows():
            item = {}
            for c in keep_cols:
                if c in row.index:
                    v = row[c]
                    item[c] = round(float(v), 4) if isinstance(v, (int, float)) and c != "symbol" else v
            item["reason"] = _build_strength_reason(item)
            items.append(item)
        return items
    except Exception as exc:
        logger.warning("Failed to load strong stocks from openbb module: %s", exc)
        return []


def load_strong_stocks_with_params(
    market_type: str = "us_stock",
    top_count: Optional[int] = None,
    rsi_threshold: Optional[float] = None,
    momentum_days: Optional[list[int]] = None,
    top_volume_count: Optional[int] = None,
    sort_by: Optional[str] = None,
    min_volume_turnover: Optional[float] = None,
) -> dict[str, Any]:
    """Public entry point for the API route — supports full parameter override."""
    items = _load_strong_stocks(
        market_type,
        top_count=top_count,
        rsi_threshold=rsi_threshold,
        momentum_days=momentum_days,
        top_volume_count=top_volume_count,
        sort_by=sort_by,
        min_volume_turnover=min_volume_turnover,
    )
    filters: dict[str, Any] = {"market_type": market_type}
    if top_count is not None:
        filters["top_count"] = top_count
    if rsi_threshold is not None:
        filters["rsi_threshold"] = rsi_threshold
    if momentum_days is not None:
        filters["momentum_days"] = momentum_days
    if top_volume_count is not None:
        filters["top_volume_count"] = top_volume_count
    if sort_by is not None:
        filters["sort_by"] = sort_by
    if min_volume_turnover is not None:
        filters["min_volume_turnover"] = min_volume_turnover
    return {"stocks": items, "filters_applied": filters}


@tool("get_strong_stocks", args_schema=StrongStocksInput)
def get_strong_stocks(
    market_type: str = "us_stock",
    top_count: Optional[int] = None,
    rsi_threshold: Optional[float] = None,
    sort_by: Optional[str] = None,
    min_volume_turnover: Optional[float] = None,
) -> str:
    """Get the current strong-stock list from the monitoring pool (screening data, not advice).

    Returns a JSON array of stocks ranked by multi-period momentum,
    each with symbol, name, performance across multiple periods, and average volume.
    Supports filtering by top_count, rsi_threshold, sort_by, and min_volume_turnover.
    """
    items = _load_strong_stocks(
        market_type,
        top_count=top_count,
        rsi_threshold=rsi_threshold,
        sort_by=sort_by,
        min_volume_turnover=min_volume_turnover,
    )
    if not items:
        # Snapshot fallback
        from app.providers.ticker_cache import _load_snapshot
        snap = _load_snapshot(f"strong_stocks_{market_type}")
        if snap and isinstance(snap, dict) and snap.get("stocks"):
            items = snap["stocks"]
            logger.info("strong_stocks: using snapshot fallback for %s", market_type)
    if not items:
        return json.dumps(
            {"error": f"No strong stocks data available for {market_type}. "
             "The monitoring pool may need to be built first (run build_monitoring_pool.py)."}
        )
    return json.dumps(
        {"market_type": market_type, "count": len(items), "stocks": items},
        default=str,
        ensure_ascii=False,
    )
