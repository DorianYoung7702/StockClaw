"""
Technical indicators calculation module.
"""
import numpy as np
import pandas as pd
from typing import Optional


class TechnicalIndicators:
    """Calculate various technical indicators."""
    
    @staticmethod
    def calculate_rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
        """
        Calculate Relative Strength Index (RSI).
        
        Args:
            prices: Price array (typically close prices)
            period: RSI period (default 14)
            
        Returns:
            RSI values array
        """
        if len(prices) < period + 1:
            return np.full(len(prices), np.nan)
        
        # Calculate price changes
        deltas = np.diff(prices)
        
        # Separate gains and losses
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        # Calculate initial average gain and loss
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        
        # Initialize RSI array
        rsi = np.full(len(prices), np.nan)
        
        # Calculate RSI for the first valid period
        if avg_loss != 0:
            rs = avg_gain / avg_loss
            rsi[period] = 100 - (100 / (1 + rs))
        else:
            rsi[period] = 100
        
        # Calculate RSI for remaining periods using smoothed averages
        for i in range(period + 1, len(prices)):
            gain = gains[i - 1]
            loss = losses[i - 1]
            
            # Smoothed averages (Wilder's smoothing)
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
            
            if avg_loss != 0:
                rs = avg_gain / avg_loss
                rsi[i] = 100 - (100 / (1 + rs))
            else:
                rsi[i] = 100
        
        return rsi
    
    @staticmethod
    def calculate_sma(prices: np.ndarray, period: int) -> np.ndarray:
        """
        Calculate Simple Moving Average.
        
        Args:
            prices: Price array
            period: Moving average period
            
        Returns:
            SMA array
        """
        if len(prices) < period:
            return np.full(len(prices), np.nan)
        
        sma = np.full(len(prices), np.nan)
        for i in range(period - 1, len(prices)):
            sma[i] = np.mean(prices[i - period + 1:i + 1])
        
        return sma
    
    @staticmethod
    def calculate_ema(prices: np.ndarray, period: int) -> np.ndarray:
        """
        Calculate Exponential Moving Average.
        
        Args:
            prices: Price array
            period: EMA period
            
        Returns:
            EMA array
        """
        if len(prices) < period:
            return np.full(len(prices), np.nan)
        
        alpha = 2.0 / (period + 1)
        ema = np.full(len(prices), np.nan)
        
        # Initialize with SMA
        ema[period - 1] = np.mean(prices[:period])
        
        # Calculate EMA for remaining periods
        for i in range(period, len(prices)):
            ema[i] = alpha * prices[i] + (1 - alpha) * ema[i - 1]
        
        return ema
    
    @staticmethod
    def calculate_bollinger_bands(prices: np.ndarray, period: int = 20, std_dev: float = 2.0) -> tuple:
        """
        Calculate Bollinger Bands.
        
        Args:
            prices: Price array
            period: Moving average period
            std_dev: Standard deviation multiplier
            
        Returns:
            Tuple of (upper_band, middle_band, lower_band)
        """
        sma = TechnicalIndicators.calculate_sma(prices, period)
        
        upper_band = np.full(len(prices), np.nan)
        lower_band = np.full(len(prices), np.nan)
        
        for i in range(period - 1, len(prices)):
            window = prices[i - period + 1:i + 1]
            std = np.std(window)
            upper_band[i] = sma[i] + (std_dev * std)
            lower_band[i] = sma[i] - (std_dev * std)
        
        return upper_band, sma, lower_band
    
    @staticmethod
    def calculate_macd(prices: np.ndarray, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> tuple:
        """
        Calculate MACD (Moving Average Convergence Divergence).
        
        Args:
            prices: Price array
            fast_period: Fast EMA period
            slow_period: Slow EMA period
            signal_period: Signal line EMA period
            
        Returns:
            Tuple of (macd_line, signal_line, histogram)
        """
        ema_fast = TechnicalIndicators.calculate_ema(prices, fast_period)
        ema_slow = TechnicalIndicators.calculate_ema(prices, slow_period)
        
        macd_line = ema_fast - ema_slow
        signal_line = TechnicalIndicators.calculate_ema(macd_line, signal_period)
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    @staticmethod
    def get_latest_value(indicator: np.ndarray) -> Optional[float]:
        """
        Get the latest (most recent) value from an indicator array.
        
        Args:
            indicator: Indicator array
            
        Returns:
            Latest non-NaN value or None
        """
        # Find the last non-NaN value
        valid_indices = ~np.isnan(indicator)
        if np.any(valid_indices):
            return float(indicator[valid_indices][-1])
        return None
