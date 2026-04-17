"""
Data aggregation module for converting 1-hour data to 2-hour and 4-hour candles.
"""
import pandas as pd
import numpy as np
from typing import Optional
from utils import format_symbol_name


class DataAggregator:
    """Aggregate 1-hour data into 4-hour candles."""
    
    @staticmethod
    def _filter_and_aggregate_trading_hours(df_30m: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        Filter 30-minute data for regular US trading hours and aggregate to 4-hour candles.
        
        Args:
            df_30m: DataFrame with 30-minute OHLCV data
            
        Returns:
            DataFrame with 4-hour OHLCV data for regular trading hours
        """
        if df_30m.empty:
            return None
        
        # Ensure we have the required columns
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df_30m.columns for col in required_cols):
            raise ValueError(f"DataFrame must contain columns: {required_cols}")
        
        # Ensure date column is datetime
        if 'date' in df_30m.columns:
            df = df_30m.copy()
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
        elif df_30m.index.name == 'date' or isinstance(df_30m.index, pd.DatetimeIndex):
            df = df_30m.copy()
        else:
            raise ValueError("DataFrame must have a datetime index or 'date' column")
        
        # Convert to UTC+8 timezone for trading hours filtering
        if df.index.tz is None:
            df = df.tz_localize('UTC').tz_convert('Asia/Shanghai')
        else:
            df = df.tz_convert('Asia/Shanghai')
        
        # Filter for regular US trading hours in UTC+8
        # Regular hours: 21:30-01:30 and 01:30-04:00 (next day)
        # Winter time: 22:30-02:30 and 02:30-05:00 (next day)
        trading_hours_mask = (
            # First session: 21:30-01:30 (or 22:30-02:30 in winter)
            ((df.index.hour == 21) & (df.index.minute >= 30)) |  # 21:30-21:59
            ((df.index.hour >= 22) & (df.index.hour <= 23)) |    # 22:00-23:59
            ((df.index.hour == 0) & (df.index.minute <= 29)) |   # 00:00-00:29
            ((df.index.hour == 1) & (df.index.minute <= 29)) |   # 01:00-01:29
            # Second session: 01:30-04:00 (or 02:30-05:00 in winter)
            ((df.index.hour == 1) & (df.index.minute >= 30)) |   # 01:30-01:59
            ((df.index.hour >= 2) & (df.index.hour <= 3)) |      # 02:00-03:59
            ((df.index.hour == 4) & (df.index.minute == 0))      # 04:00
        )
        
        # Apply trading hours filter
        df_trading = df[trading_hours_mask]
        
        if df_trading.empty:
            return None
        
        # Group by date to create 4-hour periods within trading hours
        # We'll create two 4-hour periods per trading day
        df_trading = df_trading.copy()  # Avoid SettingWithCopyWarning
        df_trading['trading_date'] = df_trading.index.date
        df_trading['session'] = df_trading.index.hour.map(
            lambda h: 1 if h >= 21 or h <= 1 else 2  # Session 1: 21:30-01:30, Session 2: 01:30-04:00
        )
        
        # Aggregate by trading date and session
        agg_data = df_trading.groupby(['trading_date', 'session']).agg({
            'open': 'first',      # First open price in the session
            'high': 'max',        # Highest high in the session
            'low': 'min',         # Lowest low in the session
            'close': 'last',      # Last close price in the session
            'volume': 'sum'       # Sum of volume in the session
        }).reset_index()
        
        # Create proper datetime index for the aggregated data
        agg_data['date'] = pd.to_datetime(agg_data['trading_date'])
        # Add session start time
        agg_data['date'] = agg_data.apply(
            lambda row: row['date'] + pd.Timedelta(hours=21 if row['session'] == 1 else 1, minutes=30),
            axis=1
        )
        
        # Drop helper columns
        agg_data = agg_data.drop(['trading_date', 'session'], axis=1)
        
        # Set date as index and convert back to UTC
        agg_data = agg_data.set_index('date')
        if agg_data.index.tz is None:
            agg_data = agg_data.tz_localize('Asia/Shanghai').tz_convert('UTC')
        else:
            agg_data = agg_data.tz_convert('UTC')
        
        # Reset index to have 'date' column
        agg_data = agg_data.reset_index()
        
        return agg_data
    
    @staticmethod
    def _filter_and_aggregate_trading_hours_1h(df_1h: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        Aggregate 1-hour data into 4-hour candles using reverse grouping method.
        Groups are created from the end, ensuring the last 4 1-hour candles form the last 4-hour candle.
        This matches TradingView's approach.
        
        Args:
            df_1h: DataFrame with 1-hour OHLCV data
            
        Returns:
            DataFrame with 4-hour OHLCV data
        """
        if df_1h.empty:
            return None
        
        # Ensure we have the required columns
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df_1h.columns for col in required_cols):
            raise ValueError(f"DataFrame must contain columns: {required_cols}")
        
        # Ensure date column is datetime
        if 'date' in df_1h.columns:
            df = df_1h.copy()
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
        elif df_1h.index.name == 'date' or isinstance(df_1h.index, pd.DatetimeIndex):
            df = df_1h.copy()
        else:
            raise ValueError("DataFrame must have a datetime index or 'date' column")
        
        # Sort by date to ensure proper aggregation
        df = df.sort_index()
        
        # Create reverse groups: start from the end and work backwards
        # This ensures the last 4 1-hour candles form the last 4-hour candle
        total_rows = len(df)
        df['reverse_group'] = (total_rows - 1 - np.arange(total_rows)) // 4
        
        # Aggregate by reverse group
        agg_data = df.groupby('reverse_group').agg({
            'open': 'first',      # First open price in the group (chronologically)
            'high': 'max',        # Highest high in the group
            'low': 'min',         # Lowest low in the group
            'close': 'last',      # Last close price in the group (chronologically)
            'volume': 'sum'       # Sum of volume in the group
        }).reset_index()
        
        # Create proper datetime index using the first timestamp of each group
        # Get the first timestamp for each reverse group and create a mapping
        group_info = df.groupby('reverse_group').first()
        agg_data['date'] = agg_data['reverse_group'].apply(lambda x: group_info.index[x])
        
        # Drop the reverse_group column
        agg_data = agg_data.drop('reverse_group', axis=1)
        
        # Sort by date to get chronological order
        agg_data = agg_data.sort_values('date')
        
        # Print Kline timestamp for debug
        print("4-hour K-line timestamps:")
        print(agg_data['date'])
        
        return agg_data
    
    @staticmethod
    def get_4h_data_from_1h(df_1h: pd.DataFrame) -> pd.DataFrame:
        """Convert 1-hour K-lines to 4-hour K-lines."""
        df = df_1h.copy()
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        else:
            raise ValueError("DataFrame must have a 'date' column")

        # Build aggregation dictionary
        agg = {
            'date': 'first',
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }

        # For any other columns not in agg, use 'first' (keeps vwap, split_ratio, dividend, etc.)
        for col in df.columns:
            if col not in agg:
                agg[col] = 'first'

        # Group every `period` rows in original order
        groups = np.arange(len(df)) // 4
        out = df.groupby(groups, sort=False).agg(agg).reset_index(drop=True)

        # Optional: ensure types (you can remove or adapt these lines if you prefer)
        out['open'] = out['open'].astype(float)
        out['high'] = out['high'].astype(float)
        out['low']  = out['low'].astype(float)
        out['close'] = out['close'].astype(float)
        out['volume'] = out['volume'].astype(df['volume'].dtype)

        return out
    
    @staticmethod
    def get_2h_data_from_1h(df_1h: pd.DataFrame) -> pd.DataFrame:
        """Convert 1-hour K-lines to 2-hour K-lines."""
        df = df_1h.copy()
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        else:
            raise ValueError("DataFrame must have a 'date' column")

        # Build aggregation dictionary
        agg = {
            'date': 'first',
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }

        # For any other columns not in agg, use 'first' (keeps vwap, split_ratio, dividend, etc.)
        for col in df.columns:
            if col not in agg:
                agg[col] = 'first'

        # Group every 2 rows in original order
        groups = np.arange(len(df)) // 2
        out = df.groupby(groups, sort=False).agg(agg).reset_index(drop=True)

        # Optional: ensure types (you can remove or adapt these lines if you prefer)
        out['open'] = out['open'].astype(float)
        out['high'] = out['high'].astype(float)
        out['low']  = out['low'].astype(float)
        out['close'] = out['close'].astype(float)
        out['volume'] = out['volume'].astype(df['volume'].dtype)

        return out