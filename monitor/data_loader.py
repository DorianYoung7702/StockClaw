"""
Enhanced data loader with caching capabilities for stock monitoring.
"""
import pandas as pd
import json
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from config import Config, MarketType


class DataLoader:
    """Enhanced data loader with caching and monitoring pool construction."""
    
    def __init__(self, config: Config):
        self.config = config
        self.cache_dir = Path(config.cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
    
    def format_volume(self, vol: float) -> str:
        """Format volume to a string like 1.23k, 5b, 100m, etc.
        
        Args:
            vol: Volume in float
            
        Returns:
            Formatted volume string
        """
        if vol < 1e3:
            return f"{vol:.0f}"
        elif vol < 1e6:
            return f"{vol/1e3:.1f}k"
        elif vol < 1e9:
            return f"{vol/1e6:.1f}m"
        else:
            return f"{vol/1e9:.1f}b"

    def read_symbol_list_from_csv(self, csv_path: str, top_n: int = 2000) -> List[Dict[str, str]]:
        """
        Read symbol list from CSV file, sorted by trading volume * price.
        Supports both English and Chinese CSV headers.
        
        Args:
            csv_path: Path to the CSV file
            top_n: Number of top symbols to return
            
        Returns:
            List of dictionaries with 'symbol' and 'name' keys
        """
        df = pd.read_csv(csv_path)
        
        # Detect CSV format based on headers
        is_chinese_format = self._detect_chinese_format(df.columns)
        
        if is_chinese_format:
            # Chinese format: "代码", "成交量", "最新价", "名称"
            symbol_col = "代码"
            volume_col = "成交量"
            price_col = "最新价"
            name_col = "名称"
        else:
            # English format: "Symbol", "Volume", "Price", "Name"
            symbol_col = "Symbol"
            volume_col = "Volume"
            price_col = "Price"
            name_col = "Name"
        
        # Clean and convert data
        df[volume_col] = df[volume_col].replace("-", 0.0)
        df[price_col] = df[price_col].replace("-", 0.0)
        df[volume_col] = pd.to_numeric(df[volume_col], errors='coerce').fillna(0)
        df[price_col] = pd.to_numeric(df[price_col], errors='coerce').fillna(0)
        
        # Calculate trading weight (volume * price)
        df["Weight"] = df[volume_col] * df[price_col]
        
        # Sort by weight and return top symbols with names
        df_sorted = df.sort_values(by="Weight", ascending=False)
        result = []
        for _, row in df_sorted.head(top_n).iterrows():
            result.append({
                'symbol': row[symbol_col],
                'name': row[name_col] if name_col in df.columns else row[symbol_col]  # fallback to symbol if name not available
            })
        return result
    
    def _detect_chinese_format(self, columns: pd.Index) -> bool:
        """
        Detect if CSV uses Chinese headers.
        
        Args:
            columns: DataFrame columns
            
        Returns:
            True if Chinese format detected, False otherwise
        """
        # Check for Chinese characters in column names
        chinese_indicators = ["代码", "成交量", "最新价"]
        return any(indicator in str(col) for col in columns for indicator in chinese_indicators)
    
    def _get_cache_path(self, cache_name: str) -> Path:
        """Get cache file path."""
        return self.cache_dir / f"{cache_name}.json"
    
    def _is_cache_valid(self, cache_path: Path) -> bool:
        """Check if cache is still valid based on expiry time."""
        if not cache_path.exists():
            return False
        
        return True

        cache_time = datetime.fromtimestamp(cache_path.stat().st_mtime)
        expiry_time = cache_time + timedelta(hours=self.config.cache_expiry_hours)
        return datetime.now() < expiry_time
    
    def is_cache_valid(self, cache_name: str) -> bool:
        """
        Check if a specific cache is valid.
        
        Args:
            cache_name: Name of the cache to check
            
        Returns:
            True if cache exists and is valid, False otherwise
        """
        cache_path = self._get_cache_path(cache_name)
        return self._is_cache_valid(cache_path)
    
    def _load_from_cache(self, cache_name: str) -> Optional[Dict]:
        """Load data from cache if valid."""
        cache_path = self._get_cache_path(cache_name)
        
        if self._is_cache_valid(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                print(f"Loaded {cache_name} from cache")
                return data
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading cache {cache_name}: {e}")
        
        return None
    
    def _save_to_cache(self, cache_name: str, data: Dict) -> None:
        """Save data to cache."""
        cache_path = self._get_cache_path(cache_name)
        
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"Saved {cache_name} to cache")
        except IOError as e:
            print(f"Error saving cache {cache_name}: {e}")
    
    def get_top_volume_symbols(self, market_type: MarketType = MarketType.US_STOCK) -> List[str]:
        """
        Get top symbols by trading volume from monitoring pool cache.
        
        Args:
            market_type: Market type to get symbols for
        
        Returns:
            List of top volume symbols
        """
        # Load monitoring pool data
        monitoring_pool_df = self.get_monitoring_pool_data(market_type, flag_top_only=False)
        
        if monitoring_pool_df.empty:
            print("No monitoring pool data available")
            return []
        
        # Get top volume symbols
        top_symbols = monitoring_pool_df.head(self.config.top_volume_count)['symbol'].tolist()
        return top_symbols
    
    def get_performance_symbols(self, market_type: MarketType = MarketType.US_STOCK) -> List[str]:
        """
        Get top performing symbols for different periods from monitoring pool cache.
        Returns symbols sorted by 20-day performance in descending order.
        
        Args:
            market_type: Market type to get symbols for
        
        Returns:
            List of top performing symbols sorted by 20d performance (desc)
        """

        monitoring_pool_df = self.get_monitoring_pool_data(market_type)

        if monitoring_pool_df.empty:
            print("No monitoring pool data available")
            return []

        top_count = self.config.top_performers_count
        if market_type == MarketType.US_STOCK:
            monitoring_pool_df = monitoring_pool_df[monitoring_pool_df['volume_5d_avg'] >= 6e8]
            top_count = min(top_count, 15)
        elif market_type == MarketType.ETF:
            monitoring_pool_df = monitoring_pool_df[monitoring_pool_df['volume_5d_avg'] >= 20e6] # 20m
            top_count = min(top_count, 15)
        elif market_type == MarketType.HK_STOCK:
            monitoring_pool_df = monitoring_pool_df[monitoring_pool_df['volume_5d_avg'] >= 5e7] # 5000w HKD
            top_count = min(top_count, 20)

        # 优先用 momentum_score 综合���分排序（含相对强度+量价+趋势平滑）
        # 兼容旧缓存（无 momentum_score 字段时降级到 performance_20d）
        sort_col = 'momentum_score' if 'momentum_score' in monitoring_pool_df.columns else 'performance_20d'

        # 主排序用 momentum_score 综合评分（相对强度+量价+���势平滑），长周期仍按涨幅
        symbol_performance_20d = monitoring_pool_df.sort_values(by=sort_col, ascending=False).head(top_count)['symbol'].tolist()
        symbol_performance_40d = monitoring_pool_df.sort_values(by="performance_40d", ascending=False).head(top_count)['symbol'].tolist()
        symbol_performance_90d = monitoring_pool_df.sort_values(by="performance_90d", ascending=False).head(top_count)['symbol'].tolist()
        symbol_performance_180d = monitoring_pool_df.sort_values(by="performance_180d", ascending=False).head(top_count)['symbol'].tolist()

        # get names
        name_performance_20d = monitoring_pool_df.sort_values(by=sort_col, ascending=False).head(top_count)['name'].tolist()
        name_performance_40d = monitoring_pool_df.sort_values(by="performance_40d", ascending=False).head(top_count)['name'].tolist()
        name_performance_90d = monitoring_pool_df.sort_values(by="performance_90d", ascending=False).head(top_count)['name'].tolist()
        name_performance_180d = monitoring_pool_df.sort_values(by="performance_180d", ascending=False).head(top_count)['name'].tolist()
        

        # 美化调试输出 - 转换为中文和Markdown表格格式
        volume_map = monitoring_pool_df.set_index('symbol')['volume_5d_avg'].to_dict()
        volume_map = {k: self.format_volume(v) for k, v in volume_map.items()}
        
        def print_performance_table(period_name: str, symbols: List[str], names: List[str], performance_col: str, market_type: str):
            """打印性能表格"""
            print(f"\n## {period_name} 表现最佳股票")
            if market_type == MarketType.HK_STOCK:
                print("| 排名 | 代码 | 名称 | 收益率 | 5日平均成交量 |")
                print("|------|------|------|--------|--------------|")
            else:
                print("| 排名 | 股票代码 | 收益率 | 5日平均成交量 |")
                print("|------|----------|--------|--------------|")
            
            for i, symbol in enumerate(symbols, 1):
                performance = monitoring_pool_df.loc[monitoring_pool_df['symbol'] == symbol][performance_col].values[0]
                volume = volume_map.get(symbol, '0')
                if market_type == MarketType.HK_STOCK:
                    name = names[i - 1]
                    code = str(symbol).replace('.HK', '')
                    print(f"| {i} | {code} | {name} | {performance:.1f}% | {volume} |")
                else:
                    print(f"| {i} | {symbol} | {performance:.1f}% | {volume} |")
        
        # 打印各期间表现表格
        print_performance_table("20日", symbol_performance_20d, name_performance_20d, 'performance_20d', market_type)
        print_performance_table("40日", symbol_performance_40d, name_performance_40d, 'performance_40d', market_type)
        print_performance_table("90日", symbol_performance_90d, name_performance_90d, 'performance_90d', market_type)
        print_performance_table("180日", symbol_performance_180d, name_performance_180d, 'performance_180d', market_type)

        # Combine all symbols and remove duplicates
        all_performance_symbols = set(symbol_performance_20d + symbol_performance_40d + symbol_performance_90d + symbol_performance_180d)
        
        # Create a mapping of symbol to 20d performance for sorting
        performance_map = monitoring_pool_df.set_index('symbol')['performance_20d'].to_dict()
        
        # Sort by 20d performance in descending order
        symbol_to_name = monitoring_pool_df.set_index('symbol')['name'].to_dict()
        sorted_symbols = sorted(all_performance_symbols, key=lambda x: performance_map.get(x, 0), reverse=True)

        # 打印按20日表现排序的综合表格
        print(f"\n## 综合表现排行榜 (按20日收益率排序)")
        # 显示评估标准
        has_momentum = 'momentum_score' in monitoring_pool_df.columns
        if has_momentum:
            bench = '^HSI' if market_type == MarketType.HK_STOCK else 'SPY'
            print(f"> **评估标准**：综合动量评分（相对强度×40% + 量价配合×30% + 趋势平滑×30%）")
            print(f"> - 相对强度：个股涨幅 - {bench} 同期涨幅（超额收益）")
            print(f"> - 量价配合：近20日均量 / 前20日均量（>1 代表放量上涨）")
            print(f"> - 趋势平滑：近20日价格线性回归 R²（越高越平稳）")
            print(f"> 20日涨幅仅供参考，排名以综合评分为准")
            print()
        if market_type == MarketType.HK_STOCK:
            print("| 排名 | 代码 | 名称 | 20日收益率 | 5日平均成交量 |")
            print("|------|------|------|------------|--------------|")
        else:
            print("| 排名 | 股票代码 | 20日收益率 | 5日平均成交量 |")
            print("|------|----------|------------|--------------|")
        
        for i, symbol in enumerate(sorted_symbols, 1):
            performance = performance_map.get(symbol, 0)
            volume = volume_map.get(symbol, '0')
            if market_type == MarketType.HK_STOCK:
                code = str(symbol).replace('.HK', '')
                name = symbol_to_name.get(symbol, symbol)
                print(f"| {i} | {code} | {name} | {performance:.1f}% | {volume} |")
            else:
                print(f"| {i} | {symbol} | {performance:.1f}% | {volume} |")
        return sorted_symbols
    
    def get_performance_symbols_in_detail(self, market_type: MarketType = MarketType.US_STOCK) -> Tuple[List[str], List[str], List[float], List[str]]:
        """
        Get top symbols, names, 20d performance, and 5d average volume.
        
        Args:
            market_type: Market type to get symbols for
        
        Returns:
            four lists: symbols, names, performances, volumes
        """
        monitoring_pool_df = self.get_monitoring_pool_data(market_type)

        if monitoring_pool_df.empty:
            print("No monitoring pool data available")
            return [], [], [], []

        # Filter by volume
        top_count = self.config.top_performers_count
        if market_type == MarketType.US_STOCK:
            monitoring_pool_df = monitoring_pool_df[monitoring_pool_df['volume_5d_avg'] >= 6e8]
            top_count = min(top_count,15)
        elif market_type == MarketType.ETF:
            monitoring_pool_df = monitoring_pool_df[monitoring_pool_df['volume_5d_avg'] >= 20e6] # 20m
            top_count = min(top_count,15)
        elif market_type == MarketType.HK_STOCK:
            monitoring_pool_df = monitoring_pool_df[monitoring_pool_df['volume_5d_avg'] >= 5e7] # 5000w HKD
            top_count = min(top_count, 20)
        
        # 优先用 momentum_score 综合评分排序，兼容旧缓存
        sort_col = 'momentum_score' if 'momentum_score' in monitoring_pool_df.columns else 'performance_20d'

        # Get top performing symbols for each period
        symbol_performance_20d = monitoring_pool_df.sort_values(by=sort_col, ascending=False).head(top_count)['symbol'].tolist()
        symbol_performance_40d = monitoring_pool_df.sort_values(by="performance_40d", ascending=False).head(top_count)['symbol'].tolist()
        symbol_performance_90d = monitoring_pool_df.sort_values(by="performance_90d", ascending=False).head(top_count)['symbol'].tolist()
        symbol_performance_180d = monitoring_pool_df.sort_values(by="performance_180d", ascending=False).head(top_count)['symbol'].tolist()
        
        # Combine all symbols and remove duplicates
        all_performance_symbols = set(symbol_performance_20d + symbol_performance_40d + symbol_performance_90d + symbol_performance_180d)
        
        # Create mappings for sorting
        performance_map = monitoring_pool_df.set_index('symbol')['performance_20d'].to_dict()
        volume_map = monitoring_pool_df.set_index('symbol')['volume_5d_avg'].to_dict()
        
        # Check if name column exists (for backward compatibility)
        if 'name' in monitoring_pool_df.columns:
            name_map = monitoring_pool_df.set_index('symbol')['name'].to_dict()
        else:
            # Fallback: use symbol as name if name column doesn't exist
            name_map = {symbol: symbol for symbol in monitoring_pool_df['symbol']}
        
        # Sort by 20d performance in descending order
        sorted_symbols = sorted(all_performance_symbols, key=lambda x: performance_map.get(x, 0), reverse=True)
        sorted_names = [name_map.get(x, x) for x in sorted_symbols]  # fallback to symbol if name not found
        sorted_performances = [performance_map.get(x, 0) for x in sorted_symbols]
        sorted_volumes = [self.format_volume(volume_map.get(x, 0)) for x in sorted_symbols]
        
        return sorted_symbols, sorted_names, sorted_performances, sorted_volumes

    def get_performance_symbols_separated(self, market_type: MarketType = MarketType.US_STOCK) -> Dict[str, List[str]]:
        """
        Get top performing symbols for different periods from monitoring pool cache.
        
        Args:
            market_type: Market type to get symbols for
        
        Returns:
            Dictionary with performance periods as keys and lists of symbols as values
        """
        monitoring_pool_df = self.get_monitoring_pool_data(market_type)

        if monitoring_pool_df.empty:
            print("No monitoring pool data available")
            return {}

        symbol_performance_20d = monitoring_pool_df.sort_values(by="performance_20d", ascending=False).head(self.config.top_performers_count)['symbol'].tolist()
        symbol_performance_40d = monitoring_pool_df.sort_values(by="performance_40d", ascending=False).head(self.config.top_performers_count)['symbol'].tolist()
        symbol_performance_90d = monitoring_pool_df.sort_values(by="performance_90d", ascending=False).head(self.config.top_performers_count)['symbol'].tolist()
        symbol_performance_180d = monitoring_pool_df.sort_values(by="performance_180d", ascending=False).head(self.config.top_performers_count)['symbol'].tolist()

        return {
            "20d": symbol_performance_20d,
            "40d": symbol_performance_40d,
            "90d": symbol_performance_90d,
            "180d": symbol_performance_180d
        }
        

    def get_monitoring_pool_data(self, market_type: MarketType = MarketType.US_STOCK, flag_top_only: bool = True) -> pd.DataFrame:
        """
        Get monitoring pool data from cache.
        
        Args:
            market_type: Market type to get data for
        
        Returns:
            DataFrame with monitoring pool data or empty DataFrame if not available
        """
        cache_name = self.config.get_cache_name_for_market(market_type)
        cached_data = self._load_from_cache(cache_name)
        
        if cached_data is not None and 'monitoring_pool' in cached_data:
            try:
                df = pd.DataFrame(cached_data['monitoring_pool'])
                print(f"Loaded monitoring pool data from cache: {len(df)} symbols")
                if flag_top_only:
                    # sort by volume
                    df = df.sort_values(by='volume_5d_avg', ascending=False)
                    df = df.head(min(self.config.top_volume_count, len(df)))
                return df
            except Exception as e:
                print(f"Error loading monitoring pool data: {e}")
        
        print("No valid monitoring pool data in cache")
        return pd.DataFrame()
    
