"""
Market condition checker for determining bearish patterns in major ETFs.
"""
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
from openbb import obb
from config import Config
from data_aggregator import DataAggregator
import yfinance as yf
from utils import format_symbol_name
from config import MarketType


class MarketConditionChecker:
    """Check market conditions based on major ETF patterns."""
    
    def __init__(self, config: Config):
        self.config = config
        self.etf_symbols_us = config.market_etfs_us
        self.etf_symbols_hk = config.market_etfs_hk
        self.threshold = config.market_condition_threshold
    
    def _is_bearish_pattern(self, df: pd.DataFrame) -> bool:
        """
        Check if a single ETF shows bearish pattern.
        
        Bearish conditions:
        1. close < open (red candle)
        2. close < 0.5 * (high + low) (close below midpoint)
        
        Args:
            df: DataFrame with OHLC data
            
        Returns:
            True if bearish pattern detected
        """
        if df.empty or len(df) < 1:
            return False
        
        latest = df.iloc[-1]
        
        # Check for required columns
        required_cols = ['open', 'high', 'low', 'close']
        if not all(col in latest for col in required_cols):
            return False
        
        # Bearish condition 1: close < open
        bearish_1 = latest['close'] < latest['open']
        
        # Bearish condition 2: close < midpoint of high and low
        midpoint = 0.5 * (latest['high'] + latest['low'])
        bearish_2 = latest['close'] < midpoint
        
        # Return True if either condition is met
        return bearish_1 or bearish_2
    
    def _fetch_etf_data(self, symbol: str, timeframe: str, limit: int = 1) -> Optional[pd.DataFrame]:
        """
        Fetch ETF data using OpenBB.
        
        Args:
            symbol: ETF symbol
            timeframe: Timeframe ('1d' for daily, '4h' for 4-hour)
            limit: Number of periods to fetch
            
        Returns:
            DataFrame with OHLC data or None if failed
        """
        try:
            # Set up OpenBB with token if available
            if self.config.openbb_token:
                obb.account.login(token=self.config.openbb_token)
            
            # Fetch data based on timeframe
            if timeframe == '1d':
                # data = obb.equity.price.historical(
                #     symbol=format_symbol_name(symbol),
                #     interval='1d',
                #     provider='yfinance',  # Use yfinance for daily data
                #     limit=limit
                # )
                data = yf.Ticker(symbol).history(period='1mo', interval='1d')
                if data is not None:
                    return data
                else:
                    print(f"Failed to get 1d data for {symbol}")
                    return None
            elif timeframe == '4h':
                data = yf.Ticker(symbol).history(period='1mo', interval='4h')
                if data is not None:
                    return data
                else:
                    print(f"Failed to get 4h data for {symbol}")
                    return None
            else:
                print(f"Unsupported timeframe: {timeframe}")
                return None
            
            # Handle OBBject response
            if data is None:
                print(f"No data received for {symbol} on {timeframe}")
                return None
            
            # Extract results from OBBject
            if hasattr(data, 'results') and data.results:
                df = pd.DataFrame([item.model_dump() for item in data.results])
                if df.empty:
                    print(f"Empty DataFrame for {symbol} on {timeframe}")
                    return None
                return df
            else:
                print(f"No results in data for {symbol} on {timeframe}")
                return None
            
        except Exception as e:
            print(f"Error fetching data for {symbol} on {timeframe}: {e}")
            return None
    
    def check_market_condition(self, timeframe: str, market_type: MarketType) -> Tuple[bool, Dict[str, bool]]:
        """
        Check market condition for a specific timeframe.
        
        Args:
            timeframe: '1d' for daily or '4h' for 4-hour
            
        Returns:
            Tuple of (is_bearish_market, individual_etf_conditions)
        """
        etf_conditions = {}
        bearish_count = 0
        
        print(f"Checking market condition for {timeframe} timeframe...")
        
        if market_type == MarketType.US_STOCK:
            etf_symbols = self.etf_symbols_us
        elif market_type == MarketType.HK_STOCK:
            etf_symbols = self.etf_symbols_hk
        else:
            raise ValueError(f"Unsupported market type: {market_type}")
        
        for symbol in etf_symbols:
            print(f"  Fetching data for {symbol}...")
            df = self._fetch_etf_data(symbol, timeframe, limit=7)
            
            if df is not None:
                is_bearish = self._is_bearish_pattern(df)
                etf_conditions[symbol] = is_bearish
                
                if is_bearish:
                    bearish_count += 1
                    print(f"    {symbol}: BEARISH")
                else:
                    print(f"    {symbol}: Not bearish")
            else:
                etf_conditions[symbol] = False
                print(f"    {symbol}: No data available")
        
        # Check if enough ETFs are bearish
        is_bearish_market = bearish_count >= self.threshold
        
        print(f"Market condition: {bearish_count}/{len(etf_symbols)} ETFs bearish")
        print(f"Alert trigger: {'YES' if is_bearish_market else 'NO'}")
        
        return is_bearish_market, etf_conditions
    
    def check_all_timeframes(self, market_type: MarketType) -> Dict[str, Tuple[bool, Dict[str, bool]]]:
        """
        Check market conditions for all configured timeframes.
        
        Returns:
            Dictionary mapping timeframe to (is_bearish, etf_conditions)
        """
        results = {}
        
        for timeframe in self.config.timeframes:
            results[timeframe] = self.check_market_condition(timeframe, market_type)
        
        return results
    
    def should_trigger_alerts(self, market_type: MarketType) -> bool:
        """
        Check if alerts should be triggered based on market conditions.
        
        Returns:
            True if alerts should be triggered
        """
        timeframe_results = self.check_all_timeframes(market_type)
        
        # Alerts should be triggered if ANY timeframe shows bearish conditions
        for timeframe, (is_bearish, _) in timeframe_results.items():
            if is_bearish:
                return True
        
        return False
