#!/usr/bin/env python3
"""
Main orchestrator for the US stock monitoring system.
"""
import sys
import argparse
import logging
import os
from pathlib import Path
from datetime import datetime
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
            logging.FileHandler('monitor.log', encoding='utf-8')
        ]
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Stock Monitoring System")
    parser.add_argument(
        "--market-type",
        choices=["us_stock", "etf", "hk_stock"],
        required=True,
        help="Market type to analyze"
    )
    parser.add_argument(
        "--log-level", 
        choices=["DEBUG", "INFO", "WARNING", "ERROR"], 
        default="INFO",
        help="Set logging level"
    )
    parser.add_argument(
        "--config-check",
        action="store_true",
        help="Check configuration and exit"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run analysis without sending notifications"
    )
    parser.add_argument(
        "--timeframe",
        choices=["2h", "4h", "1d"],
        default="4h",
        help="Timeframe to analyze"
    )
    parser.add_argument(
        "--skip-market-conditions",
        action="store_true",
        help="Skip market conditions check"
    )
    parser.add_argument(
        "--top-count",
        type=int,
        default=None,
        help="Override top_performers_count (number of strong stocks to monitor)"
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
        
        # Override top_performers_count if specified
        if args.top_count is not None:
            config.top_performers_count = args.top_count
            logger.info(f"top_performers_count overridden to: {args.top_count}")
        
        # Parse market type
        market_type = MarketType(args.market_type)
        logger.info(f"Running analysis for market type: {market_type.value}")
        
        # Configuration check
        if args.config_check:
            logger.info("Configuration check:")
            logger.info(f"  Market type: {market_type.value}")
            logger.info(f"  US Stock CSV path: {config.us_stock_csv_path}")
            logger.info(f"  ETF CSV path: {config.etf_csv_path}")
            logger.info(f"  HK Stock CSV path: {config.hk_stock_csv_path}")
            logger.info(f"  Cache directory: {config.cache_dir}")
            logger.info(f"  Top volume count: {config.top_volume_count}")
            logger.info(f"  Performance periods: {config.performance_periods}")
            logger.info(f"  Market ETFs US: {config.market_etfs_us}")
            logger.info(f"  Market ETFs HK: {config.market_etfs_hk}")
            logger.info(f"  Timeframes: {config.timeframes}")
            logger.info(f"  RSI threshold: {config.rsi_strong_threshold}")
            logger.info(f"  Feishu webhook: {'Configured' if config.feishu_webhook_url else 'Not configured'}")
            logger.info(f"  OpenBB token: {'Configured' if config.openbb_token else 'Not configured'}")
            
            # Check if CSV file exists for the specified market type
            csv_path = Path(config.get_csv_path_for_market(market_type))
            if csv_path.exists():
                logger.info(f"  CSV file exists: {csv_path.stat().st_size} bytes")
            else:
                logger.warning(f"  CSV file not found: {csv_path}")
            
            return 0
        
        # Check if CSV file exists for the specified market type
        csv_path = Path(config.get_csv_path_for_market(market_type))
        if not csv_path.exists():
            logger.error(f"CSV data file not found: {csv_path}")
            logger.error(f"Please ensure the CSV file exists for market type {market_type.value}")
            return 1
        
        # Initialize analyzer
        logger.info("Initializing stock analyzer...")
        analyzer = StockAnalyzer(config)
        
        # Run analysis
        logger.info("Starting analysis...")
        start_time = datetime.now()
        
        results = analyzer.run_full_analysis(args.timeframe, market_type, args.skip_market_conditions, args.dry_run)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Log results
        logger.info(f"Analysis completed in {duration:.2f} seconds")
        logger.info(f"Market trigger: {'YES' if results['should_trigger_alerts'] else 'NO'}")
        logger.info(f"Alerts generated: {len(results['alerts'])}")
        logger.info(f"Symbols analyzed: {len(results['analysis_results'])}")
        
        # Print summary
        summary = analyzer.get_analysis_summary(results)
        print("\n" + "="*60)
        print("ANALYSIS SUMMARY")
        print("="*60)
        print(summary)
        print("="*60)
        
        # Save results to file
        if not os.path.exists('logs'):
            os.makedirs('logs')
        results_file = f"logs/analysis_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        import json
        with open(results_file, 'w', encoding='utf-8') as f:
            # Convert non-serializable objects and handle numpy types
            def convert_numpy_types(obj):
                """Convert numpy types to native Python types for JSON serialization."""
                if hasattr(obj, 'item'):  # numpy scalar
                    return obj.item()
                elif isinstance(obj, dict):
                    return {k: convert_numpy_types(v) for k, v in obj.items()}
                elif isinstance(obj, (list, tuple)):
                    return [convert_numpy_types(item) for item in obj]
                else:
                    return obj
            
            # Convert market conditions to serializable format
            market_conditions_serializable = {}
            for timeframe, (is_bearish, etf_conditions) in results['market_conditions'].items():
                market_conditions_serializable[timeframe] = {
                    'is_bearish': bool(is_bearish),
                    'etf_conditions': {symbol: bool(is_bearish) for symbol, is_bearish in etf_conditions.items()}
                }
            
            serializable_results = {
                'timestamp': results['timestamp'].isoformat(),
                'market_conditions': market_conditions_serializable,
                'should_trigger_alerts': bool(results['should_trigger_alerts']),
                'alerts': [
                    {
                        'symbol': alert.symbol,
                        'timeframe': alert.timeframe,
                        'alert_type': alert.alert_type,
                        'rsi_value': float(alert.rsi_value),
                        'timestamp': alert.timestamp.isoformat(),
                        'message': alert.format_message()
                    }
                    for alert in results['alerts']
                ],
                'analysis_summary': {
                    'symbols_analyzed': len(results['analysis_results']),
                    'total_alerts': len(results['alerts'])
                }
            }
            
            # Convert any remaining numpy types
            serializable_results = convert_numpy_types(serializable_results)
            
            json.dump(serializable_results, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Results saved to: {results_file}")
        
        return 0
        
    except KeyboardInterrupt:
        logger.info("Analysis interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
