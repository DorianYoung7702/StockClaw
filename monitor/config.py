"""
Configuration management for the US stock monitoring system.
"""
import os
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
from enum import Enum


class MarketType(Enum):
    """Market type enumeration."""
    US_STOCK = "us_stock"
    ETF = "etf"
    HK_STOCK = "hk_stock"


@dataclass
class Config:
    """Main configuration class for the monitoring system."""
    
    # Data paths - separated by market type
    us_stock_csv_path: str = "20251020232140.csv"  # US stocks CSV
    etf_csv_path: str = "etf.csv"  # ETF CSV
    hk_stock_csv_path: str = "hk_stocks.csv"  # Hong Kong stocks CSV (future use)
    cache_dir: str = "cache"
    
    # Monitoring pool settings
    top_volume_count: int = 500
    top_performers_count: int = 10  # 每个周���取前N强势品种（可通过 --top-count 覆盖）
    performance_periods: list = None  # [15, 30, 60, 120] days
    
    # Cache settings
    cache_expiry_hours: int = 24
    
    # Technical indicators
    rsi_period: int = 20
    rsi_strong_threshold: float = 48.0
    
    # Market condition symbols
    market_etfs_us: list = None#["QQQ", "SPY", "DIA"]
    market_etfs_hk: list = None#["HSTECH.HK", "^HSI"]
    market_condition_threshold: int = 2  # At least 2 out of 3 ETFs must be bearish
    
    # Alert settings
    timeframes: list = None  # ["4h", "1d"]
    
    # Feishu webhook
    feishu_webhook_url: Optional[str] = None
    
    # OpenBB settings
    openbb_token: Optional[str] = None
    
    def __post_init__(self):
        """Initialize default values after dataclass creation."""
        if self.performance_periods is None:
            self.performance_periods = [15, 30, 60, 120]
        
        if self.market_etfs_hk is None:
            self.market_etfs_hk = ["HSTECH.HK", "^HSI"]
        if self.market_etfs_us is None:
            self.market_etfs_us = ["QQQ", "SPY", "DIA"]
        
        if self.timeframes is None:
            self.timeframes = ["4h", "1d"]
        
        # Create cache directory if it doesn't exist
        Path(self.cache_dir).mkdir(exist_ok=True)
        
        # Load environment variables
        self.feishu_webhook_url = os.getenv("FEISHU_WEBHOOK_URL", self.feishu_webhook_url)
        self.openbb_token = os.getenv("OPENBB_TOKEN", self.openbb_token)
    
    def get_csv_path_for_market(self, market_type: MarketType) -> str:
        """Get CSV path for specific market type."""
        if market_type == MarketType.US_STOCK:
            return self.us_stock_csv_path
        elif market_type == MarketType.ETF:
            return self.etf_csv_path
        elif market_type == MarketType.HK_STOCK:
            return self.hk_stock_csv_path
        else:
            raise ValueError(f"Unsupported market type: {market_type}")
    
    def get_cache_name_for_market(self, market_type: MarketType) -> str:
        """Get cache name for specific market type."""
        return f"monitoring_pool_data_{market_type.value}"


def load_config() -> Config:
    """Load configuration with environment variable overrides."""
    return Config()
