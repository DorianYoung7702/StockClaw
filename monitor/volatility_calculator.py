"""
Volatility calculation module based on the Pine Script reference implementation.
Implements low fluctuation detection using moving average convergence.
"""
import numpy as np
import pandas as pd
from typing import List, Tuple, Optional
import ta


class VolatilityCalculator:
    """Calculate volatility and detect low fluctuation conditions."""
    
    def __init__(self, lookback_period: int = 180):
        self.lookback_period = lookback_period
    
    def sma_standard(self, prices: np.ndarray, period: int) -> np.ndarray:
        """
        Calculate Simple Moving Average using ta library.
        
        Args:
            prices: Price array
            period: Moving average period
            
        Returns:
            SMA array
        """
        if len(prices) < period:
            return np.full(len(prices), np.nan)
        
        # Convert to pandas Series for ta library
        prices_series = pd.Series(prices)
        sma_series = ta.trend.sma_indicator(prices_series, window=period)
        return sma_series.values
    
    def _atr(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
        """
        Calculate Average True Range using ta library.
        
        Args:
            high: High prices
            low: Low prices  
            close: Close prices
            period: ATR period
            
        Returns:
            ATR array
        """
        if len(high) < 2:
            return np.zeros(len(high))
        
        # Convert to pandas DataFrame for ta library
        df = pd.DataFrame({
            'high': high,
            'low': low,
            'close': close
        })
        
        # Calculate ATR using ta library
        atr_series = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=period)
        return atr_series.values
    
    def nth_smallest(self, arr: np.ndarray, n: int, k: int = 1) -> np.ndarray:
        """
        返回数组中每个值的前n个值中的第k最小值
        
        参数:
            arr: 输入数组
            n: 窗口大小
            k: 第k小的值，默认为1（最小值）
        
        返回:
            result: 结果数组，长度与arr相同
        """
        if n <= 0:
            raise ValueError("n必须大于0")
        if k <= 0 or k > n:
            raise ValueError(f"k必须在1到n之间，当前k={k}, n={n}")
        
        length = len(arr)
        result = np.full(length, np.nan)  # 初始化结果数组
        
        # 对于前n-1个元素，窗口大小小于n
        for i in range(min(n, length)):
            window = arr[:i+1]
            if len(window) >= k:
                result[i] = np.partition(window, k-1)[k-1]
        
        # 对于剩余元素，使用完整的n大小窗口
        for i in range(n, length):
            window = arr[i-n+1:i+1]
            result[i] = np.partition(window, k-1)[k-1]
        
        return result

    
    def calculate_volatility_indicators(self, prices: np.ndarray, 
                                      high: np.ndarray, 
                                      low: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Calculate volatility indicators based on the Pine script reference implementation.
        
        Args:
            prices: Close prices
            high: High prices
            low: Low prices
            
        Returns:
            Tuple of (light_alert, medium_alert, heavy_alert) boolean arrays
        """
        if len(prices) < 30:
            return np.zeros(len(prices), dtype=bool), np.zeros(len(prices), dtype=bool), np.zeros(len(prices), dtype=bool)
        
        # Ensure we have enough data
        data_length = min(len(prices), self.lookback_period)
        start_idx = max(0, len(prices) - data_length)
        
        prices_window = prices[start_idx:]
        high_window = high[start_idx:]
        low_window = low[start_idx:]
        
        # Calculate multiple moving averages (exactly as Pine script)
        ma_periods = [2, 5, 7, 9, 11, 13, 15, 17, 20]
        ma_arrays = []
        
        for period in ma_periods:
            ma = self.sma_standard(prices_window, period)
            ma_arrays.append(ma)
        
        # Calculate MA max and min (exactly as Pine script)
        ma_max = np.full(len(prices_window), np.nan)
        ma_min = np.full(len(prices_window), np.nan)
        
        for i in range(len(prices_window)):
            valid_mas = [ma[i] for ma in ma_arrays if not np.isnan(ma[i])]
            if valid_mas:
                ma_max[i] = max(valid_mas)
                ma_min[i] = min(valid_mas)
        
        # Calculate MACO (Moving Average Convergence Oscillator) - exactly as Pine script
        denom = (ma_max + ma_min) * 0.5
        denom = np.where(denom == 0, np.inf, denom)
        maco = (ma_max - ma_min) / denom * 100.0
        
        # Calculate ATR
        atr = self._atr(high_window, low_window, prices_window, 20)
        
        # Calculate thresholds (exactly as Pine script)
        maco_20th = self.nth_smallest(maco, 20, 2)
        maco_40th = self.nth_smallest(maco, 40, 4)
        maco_60th = self.nth_smallest(maco, 60, 6)
        maco_80th = self.nth_smallest(maco, 80, 8)

        # Base conditions (exactly as Pine script)
        cond_atr = (ma_max - ma_min) < atr
        
        # cond_hist logic from Pine script: OR of all threshold conditions
        cond_hist = np.full(len(prices_window), False)
        for i in range(len(prices_window)):
            if not np.isnan(maco[i]):
                # Pine script: (not na(maco_20th) and maco < maco_20th) or ... or (not na(maco_80th) and maco < maco_80th)
                cond_hist[i] = (
                    (not np.isnan(maco_20th[i]) and maco[i] < maco_20th[i]) or
                    (not np.isnan(maco_40th[i]) and maco[i] < maco_40th[i]) or
                    (not np.isnan(maco_60th[i]) and maco[i] < maco_60th[i]) or
                    (not np.isnan(maco_80th[i]) and maco[i] < maco_80th[i])
                )
        
        # Calculate single conditions (exactly as Pine script)
        light_single = cond_atr | cond_hist
        medium_single = cond_atr & cond_hist
        
        # Calculate recent conditions (exactly as Pine script)
        # Pine: light_recent = (light_single ? 1 : 0) + (light_single[1] ? 1 : 0) + (light_single[2] ? 1 : 0) >= 2
        light_recent = np.full(len(prices_window), False)
        medium_recent = np.full(len(prices_window), False)
        
        for i in range(2, len(prices_window)):
            # Count how many of the last 3 periods satisfy the condition
            light_count = sum([
                light_single[i] if not np.isnan(light_single[i]) else False,
                light_single[i-1] if not np.isnan(light_single[i-1]) else False,
                light_single[i-2] if not np.isnan(light_single[i-2]) else False
            ])
            medium_count = sum([
                medium_single[i] if not np.isnan(medium_single[i]) else False,
                medium_single[i-1] if not np.isnan(medium_single[i-1]) else False,
                medium_single[i-2] if not np.isnan(medium_single[i-2]) else False
            ])
            
            light_recent[i] = light_count >= 2
            medium_recent[i] = medium_count >= 2
        
        # Calculate heavy condition (exactly as Pine script)
        # Pine: heavy = medium_single and medium_single[1] and medium_single[2]
        heavy = np.full(len(prices_window), False)
        for i in range(2, len(prices_window)):
            heavy[i] = (
                medium_single[i] and 
                medium_single[i-1] and 
                medium_single[i-2]
            )
        
        # Calculate alerts (exactly as Pine script)
        # Pine: light_alert = not light_recent[1] and light_recent
        # Pine: medium_alert = not medium_recent[1] and medium_recent  
        # Pine: heavy_alert = not heavy[1] and heavy
        light_alert = np.full(len(prices_window), False)
        medium_alert = np.full(len(prices_window), False)
        heavy_alert = np.full(len(prices_window), False)
        
        for i in range(1, len(prices_window)):
            light_alert[i] = not light_recent[i-1] and light_recent[i]
            medium_alert[i] = not medium_recent[i-1] and medium_recent[i]
            heavy_alert[i] = not heavy[i-1] and heavy[i]
        
        # Pad arrays to match original length
        def pad_array(arr, original_length):
            if len(arr) < original_length:
                padding = np.zeros(original_length - len(arr), dtype=bool)
                return np.concatenate([padding, arr])
            return arr
        
        # debug: print only last 10 elements
        if False:
            print(f"ma_max (last 10): {ma_max[-10:]}")
            print(f"ma_min (last 10): {ma_min[-10:]}")
            print(f"maco (last 10): {maco[-10:]}")
            print(f"maco_20th (last 10): {maco_20th[-10:]}")
            print(f"maco_40th (last 10): {maco_40th[-10:]}")
            print(f"maco_60th (last 10): {maco_60th[-10:]}")
            print(f"maco_80th (last 10): {maco_80th[-10:]}")
            print(f"cond_atr (last 10): {cond_atr[-10:]}")
            print(f"cond_hist (last 10): {cond_hist[-10:]}")
            print(f"light_single (last 10): {light_single[-10:]}")
            print(f"medium_single (last 10): {medium_single[-10:]}")
            print(f"light_recent (last 10): {light_recent[-10:]}")
            print(f"medium_recent (last 10): {medium_recent[-10:]}")
            print(f"heavy (last 10): {heavy[-10:]}")
            print(f"light_alert (last 10): {light_alert[-10:]}")
            print(f"medium_alert (last 10): {medium_alert[-10:]}")
            print(f"heavy_alert (last 10): {heavy_alert[-10:]}")


        return (pad_array(light_alert, len(prices)),
                pad_array(medium_alert, len(prices)),
                pad_array(heavy_alert, len(prices)))
    
    def calculate_breakout_signals(self, prices: np.ndarray, 
                                 high: np.ndarray, 
                                 low: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Calculate breakout signals based on the Pine script reference implementation.
        
        Args:
            prices: Close prices
            high: High prices
            low: Low prices
            
        Returns:
            Tuple of (breakout_signal, breakout_alert) boolean arrays
        """
        if len(prices) < 30:
            return np.zeros(len(prices), dtype=bool), np.zeros(len(prices), dtype=bool)
        
        # Get volatility indicators first
        light_alert, medium_alert, heavy_alert = self.calculate_volatility_indicators(prices, high, low)
        
        # Ensure we have enough data
        data_length = min(len(prices), self.lookback_period)
        start_idx = max(0, len(prices) - data_length)
        
        prices_window = prices[start_idx:]
        high_window = high[start_idx:]
        low_window = low[start_idx:]
        
        # Calculate ATR for breakout detection
        atr = self._atr(high_window, low_window, prices_window, 20)
        
        # Calculate heavy condition (same as in volatility indicators)
        # We need to recalculate heavy for the window
        ma_periods = [2, 5, 7, 9, 11, 13, 15, 17, 20]
        ma_arrays = []
        
        for period in ma_periods:
            ma = self.sma_standard(prices_window, period)
            ma_arrays.append(ma)
        
        # Calculate MA max and min
        ma_max = np.full(len(prices_window), np.nan)
        ma_min = np.full(len(prices_window), np.nan)
        
        for i in range(len(prices_window)):
            valid_mas = [ma[i] for ma in ma_arrays if not np.isnan(ma[i])]
            if valid_mas:
                ma_max[i] = max(valid_mas)
                ma_min[i] = min(valid_mas)
        
        # Calculate MACO
        denom = (ma_max + ma_min) * 0.5
        denom = np.where(denom == 0, np.inf, denom)
        maco = (ma_max - ma_min) / denom * 100.0
        
        # Calculate thresholds
        maco_20th = self.nth_smallest(maco, 20, 2)
        maco_40th = self.nth_smallest(maco, 40, 4)
        maco_60th = self.nth_smallest(maco, 60, 6)
        maco_80th = self.nth_smallest(maco, 80, 8)
        
        # Base conditions
        cond_atr = (ma_max - ma_min) < atr
        cond_hist = np.full(len(prices_window), False)
        for i in range(len(prices_window)):
            if not np.isnan(maco[i]):
                cond_hist[i] = (
                    (not np.isnan(maco_20th[i]) and maco[i] < maco_20th[i]) or
                    (not np.isnan(maco_40th[i]) and maco[i] < maco_40th[i]) or
                    (not np.isnan(maco_60th[i]) and maco[i] < maco_60th[i]) or
                    (not np.isnan(maco_80th[i]) and maco[i] < maco_80th[i])
                )
        
        # Calculate medium_single and heavy conditions
        medium_single = cond_atr & cond_hist
        heavy = np.full(len(prices_window), False)
        for i in range(2, len(prices_window)):
            heavy[i] = (
                medium_single[i] and 
                medium_single[i-1] and 
                medium_single[i-2]
            )
        
        # Calculate breakout conditions (exactly as Pine script)
        # Condition 1: Current or previous bar satisfies heavy
        heavy_recent = np.full(len(prices_window), False)
        for i in range(len(prices_window)):
            heavy_recent[i] = heavy[i] or (i > 0 and heavy[i-1])
        
        # Condition 2: Current bar has big amplitude (>= 0.95 * ATR20)
        big_bar = (high_window - low_window) >= 0.95 * atr
        
        # Combined breakout signal
        breakout_signal = heavy_recent & big_bar
        
        # Breakout alert (state change trigger)
        breakout_alert = np.full(len(prices_window), False)
        for i in range(1, len(prices_window)):
            breakout_alert[i] = not breakout_signal[i-1] and breakout_signal[i]
        
        # Pad arrays to match original length
        def pad_array(arr, original_length):
            if len(arr) < original_length:
                padding = np.zeros(original_length - len(arr), dtype=bool)
                return np.concatenate([padding, arr])
            return arr
        
        return (pad_array(breakout_signal, len(prices)),
                pad_array(breakout_alert, len(prices)))
    
    def calculate_all_signals(self, prices: np.ndarray, 
                             high: np.ndarray, 
                             low: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Calculate all volatility and breakout signals based on the Pine script reference.
        
        Args:
            prices: Close prices
            high: High prices
            low: Low prices
            
        Returns:
            Tuple of (light_alert, medium_alert, heavy_alert, breakout_signal, breakout_alert)
        """
        # Get volatility indicators
        light_alert, medium_alert, heavy_alert = self.calculate_volatility_indicators(prices, high, low)
        
        # Get breakout signals
        breakout_signal, breakout_alert = self.calculate_breakout_signals(prices, high, low)
        
        return light_alert, medium_alert, heavy_alert, breakout_signal, breakout_alert
    
    def is_low_volatility(self, prices: np.ndarray, high: np.ndarray, low: np.ndarray) -> bool:
        """
        Check if current period shows low volatility conditions.
        Only returns True for medium (中度) and heavy (重度) alerts as requested.
        
        Args:
            prices: Close prices
            high: High prices
            low: Low prices
            
        Returns:
            True if medium or heavy low volatility detected
        """
        light_alert, medium_alert, heavy_alert = self.calculate_volatility_indicators(prices, high, low)
        
        return medium_alert[-2] or heavy_alert[-2] or medium_alert[-1] or heavy_alert[-1]
    
    def is_breakout_signal(self, prices: np.ndarray, high: np.ndarray, low: np.ndarray) -> bool:
        """
        Check if current period shows breakout signal conditions.
        
        Args:
            prices: Close prices
            high: High prices
            low: Low prices
            
        Returns:
            True if breakout signal detected
        """
        breakout_signal, breakout_alert = self.calculate_breakout_signals(prices, high, low)
        
        # Return True if breakout alert is triggered
        if len(breakout_alert) > 0 and breakout_alert[-1]:
            return True
        
        return False
