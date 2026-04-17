"""Tool for single-stock technical analysis using monitor/ module.

Wraps TechnicalIndicators, VolatilityCalculator from the monitor module to
compute RSI, MACD, Bollinger Bands, low-volatility detection, and breakout
signals for a given symbol.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Literal, Optional

import numpy as np
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.config import get_settings

logger = logging.getLogger(__name__)


class TechnicalAnalysisInput(BaseModel):
    symbol: str = Field(description="Ticker symbol, e.g. AAPL, 0700.HK")
    timeframe: Literal["1d", "1wk"] = Field(
        default="1d",
        description="Data interval: 1d (daily) or 1wk (weekly)",
    )
    period: str = Field(
        default="6mo",
        description="Look-back period: 3mo, 6mo, 1y, 2y",
    )


def _ensure_monitor_path() -> None:
    root = str(get_settings().monitor_module_root)
    if root not in sys.path:
        sys.path.insert(0, root)


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else round(f, 4)
    except (TypeError, ValueError):
        return None


@tool("get_technical_analysis", args_schema=TechnicalAnalysisInput)
def get_technical_analysis(
    symbol: str,
    timeframe: str = "1d",
    period: str = "6mo",
) -> str:
    """Run technical analysis on a single stock using the monitor module.

    Returns RSI, MACD, Bollinger Bands, low-volatility detection, and
    breakout signals. Useful for evaluating entry/exit timing and
    identifying consolidation or breakout patterns.
    """
    from app.providers.ticker_cache import get_yf_history

    try:
        df = get_yf_history(symbol, period=period, interval=timeframe)
        if df is None or df.empty or len(df) < 30:
            return json.dumps({"error": f"Insufficient price data for {symbol} (need >=30 bars)"})

        close = df["Close"].values.astype(float)
        high = df["High"].values.astype(float)
        low = df["Low"].values.astype(float)

        _ensure_monitor_path()
        from technical_indicators import TechnicalIndicators
        from volatility_calculator import VolatilityCalculator

        ti = TechnicalIndicators()
        vc = VolatilityCalculator()

        # --- RSI ---
        rsi_arr = ti.calculate_rsi(close, period=14)
        rsi_latest = ti.get_latest_value(rsi_arr)

        # --- MACD ---
        macd_line, signal_line, histogram = ti.calculate_macd(close)
        macd_latest = ti.get_latest_value(macd_line)
        signal_latest = ti.get_latest_value(signal_line)
        hist_latest = ti.get_latest_value(histogram)

        # --- Bollinger Bands ---
        upper, middle, lower = ti.calculate_bollinger_bands(close, period=20, std_dev=2.0)
        bb_upper = _safe_float(ti.get_latest_value(upper))
        bb_middle = _safe_float(ti.get_latest_value(middle))
        bb_lower = _safe_float(ti.get_latest_value(lower))
        current_close = _safe_float(close[-1])

        bb_position = None
        if bb_upper and bb_lower and current_close and (bb_upper - bb_lower) > 0:
            bb_position = round((current_close - bb_lower) / (bb_upper - bb_lower), 4)

        # --- SMA ---
        sma_20 = _safe_float(ti.get_latest_value(ti.calculate_sma(close, 20)))
        sma_60 = _safe_float(ti.get_latest_value(ti.calculate_sma(close, 60)))

        # --- Low volatility & breakout ---
        is_low_vol = bool(vc.is_low_volatility(close, high, low))
        is_breakout = bool(vc.is_breakout_signal(close, high, low))

        # --- Trend R² (20-day) ---
        trend_r2 = None
        if len(close) >= 20:
            try:
                c20 = close[-20:]
                x = np.arange(len(c20))
                c_norm = c20 / c20[0]
                coeffs = np.polyfit(x, c_norm, 1)
                y_pred = np.polyval(coeffs, x)
                ss_res = np.sum((c_norm - y_pred) ** 2)
                ss_tot = np.sum((c_norm - c_norm.mean()) ** 2)
                trend_r2 = round(max(0.0, float(1 - ss_res / ss_tot)), 4) if ss_tot > 0 else 0.0
            except Exception:
                trend_r2 = None

        result = {
            "symbol": symbol,
            "timeframe": timeframe,
            "period": period,
            "data_points": len(close),
            "current_close": current_close,
            "rsi_14": _safe_float(rsi_latest),
            "macd": {
                "macd_line": _safe_float(macd_latest),
                "signal_line": _safe_float(signal_latest),
                "histogram": _safe_float(hist_latest),
            },
            "bollinger_bands": {
                "upper": bb_upper,
                "middle": bb_middle,
                "lower": bb_lower,
                "position": bb_position,
            },
            "sma_20": sma_20,
            "sma_60": sma_60,
            "trend_r2_20d": trend_r2,
            "low_volatility_detected": is_low_vol,
            "breakout_signal": is_breakout,
            "signal_summary": _build_signal_summary(
                rsi_latest, is_low_vol, is_breakout, bb_position, hist_latest
            ),
        }

        return json.dumps(result, default=str, ensure_ascii=False)

    except Exception as exc:
        logger.warning("get_technical_analysis failed for %s: %s", symbol, exc)
        return json.dumps({"error": f"Technical analysis failed for {symbol}: {exc}"})


def _build_signal_summary(
    rsi: Optional[float],
    low_vol: bool,
    breakout: bool,
    bb_pos: Optional[float],
    macd_hist: Optional[float],
) -> str:
    """Build a brief human-readable signal summary in Chinese."""
    parts: list[str] = []
    if rsi is not None:
        if rsi >= 70:
            parts.append("RSI超买")
        elif rsi <= 30:
            parts.append("RSI超卖")
        elif rsi >= 50:
            parts.append("RSI偏强")
        else:
            parts.append("RSI偏弱")

    if low_vol and breakout:
        parts.append("低波动+突破信号")
    elif low_vol:
        parts.append("低波动收敛中")
    elif breakout:
        parts.append("突破信号")

    if bb_pos is not None:
        if bb_pos > 0.95:
            parts.append("触及布林上轨")
        elif bb_pos < 0.05:
            parts.append("触及布林下轨")

    if macd_hist is not None:
        if macd_hist > 0:
            parts.append("MACD多头")
        else:
            parts.append("MACD空头")

    return "；".join(parts) if parts else "无明显信号"
