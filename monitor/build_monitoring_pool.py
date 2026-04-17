#!/usr/bin/env python3
"""
Standalone script to build monitoring pool from command line.
This script calls the StockAnalyzer.build_monitoring_pool method separately.
"""
import sys
import argparse
import logging
from pathlib import Path
from dotenv import load_dotenv
from config import Config, MarketType
from stock_analyzer import StockAnalyzer


def setup_logging(log_level: str = "INFO") -> None:
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('build_pool.log', encoding='utf-8')
        ]
    )


def main():
    """Main entry point for building monitoring pool."""
    parser = argparse.ArgumentParser(description="Build Stock Monitoring Pool")
    parser.add_argument(
        "--market-type",
        choices=["us_stock", "etf", "hk_stock"],
        required=True,
        help="Market type to build monitoring pool for"
    )
    parser.add_argument(
        "--log-level", 
        choices=["DEBUG", "INFO", "WARNING", "ERROR"], 
        default="INFO",
        help="Set logging level"
    )
    parser.add_argument(
        "--csv-path",
        type=str,
        help="Path to CSV file with stock symbols (overrides config)"
    )
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Force rebuild even if cache exists"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually building"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)
    
    try:
        # Load environment variables from env file
        load_dotenv('env')

        # === 启动时更新 symbol 列表（新上市/成交额>1亿）===
        from update_symbol_list import update_all_symbol_lists
        update_all_symbol_lists()

        # Load configuration
        logger.info("Loading configuration...")
        config = Config()
        
        # Parse market type
        market_type = MarketType(args.market_type)
        logger.info(f"Building monitoring pool for market type: {market_type.value}")
        
        # Get CSV path for the specified market type
        csv_path = args.csv_path if args.csv_path else config.get_csv_path_for_market(market_type)
        
        # Check if CSV file exists
        csv_file = Path(csv_path)
        if not csv_file.exists():
            logger.error(f"CSV data file not found: {csv_file}")
            logger.error(f"Please ensure the CSV file exists for market type {market_type.value} or provide --csv-path")
            return 1
        
        logger.info(f"Using CSV file for {market_type.value}: {csv_file}")
        
        # Initialize analyzer
        logger.info("Initializing stock analyzer...")
        analyzer = StockAnalyzer(config)
        
        # Setup OpenBB
        analyzer._setup_openbb()
        
        # Read symbols from CSV file
        logger.info("Reading symbols from CSV file...")
        symbols_data = analyzer.data_loader.read_symbol_list_from_csv(csv_path)
        logger.info(f"Found {len(symbols_data)} symbols in {market_type.value} CSV")
        
        if not symbols_data:
            logger.error("No symbols found in CSV file")
            return 1
        
        # Check cache if not forcing rebuild
        cache_name = config.get_cache_name_for_market(market_type)
        if not args.force_rebuild and analyzer.data_loader.is_cache_valid(cache_name):
            logger.info("Valid cache found. Use --force-rebuild to rebuild anyway.")
            cache_data = analyzer.data_loader.get_monitoring_pool_data(market_type)
            if not cache_data.empty:
                logger.info(f"Cached monitoring pool has {len(cache_data)} symbols")
                logger.info(f"Top 5 by volume: {cache_data.head()['symbol'].tolist()}")
                # return 0
        
        # Build monitoring pool
        logger.info("Building monitoring pool...")
        if not args.dry_run:
            monitoring_pool = analyzer.build_monitoring_pool(symbols_data, market_type)
        else:
            monitoring_pool = analyzer.data_loader.get_monitoring_pool_data(market_type)

        if monitoring_pool.empty:
            logger.error("Failed to build monitoring pool - no valid data found")
            return 1
        
        # Display results
        logger.info(f"Successfully built monitoring pool with {len(monitoring_pool)} symbols")
        
        high_performance_symbols = analyzer.data_loader.get_performance_symbols(market_type)

        # Print for debug
        for symbol in high_performance_symbols:
            logger.info(f"  {symbol}: {monitoring_pool.loc[monitoring_pool['symbol'] == symbol]['performance_20d'].values[0]:.1f}%")
        
        logger.info("Monitoring pool build completed successfully!")
        return 0
        
    except KeyboardInterrupt:
        logger.info("Build interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
