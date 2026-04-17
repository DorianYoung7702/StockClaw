"""
Main stock analyzer that coordinates all components for monitoring.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import yfinance as yf
from openbb import obb
from config import Config, MarketType
from data_loader import DataLoader
from volatility_calculator import VolatilityCalculator
from technical_indicators import TechnicalIndicators
from market_condition import MarketConditionChecker
from alert_system import AlertSystem, Alert
from data_aggregator import DataAggregator
from utils import format_symbol_name


class StockAnalyzer:
    """Main analyzer that coordinates all monitoring components."""
    
    def __init__(self, config: Config):
        self.config = config
        self.data_loader = DataLoader(config)
        self.volatility_calc = VolatilityCalculator()
        self.tech_indicators = TechnicalIndicators()
        self.market_checker = MarketConditionChecker(config)
        self.alert_system = AlertSystem(config)
    
    def _setup_openbb(self) -> None:
        """Setup OpenBB with authentication if token is available."""
        if self.config.openbb_token:
            try:
                obb.account.login(token=self.config.openbb_token)
                print("OpenBB authenticated successfully")
            except Exception as e:
                print(f"OpenBB authentication failed: {e}")
    
    def build_monitoring_pool(self, symbols: List[Dict[str, str]], market_type: MarketType = MarketType.US_STOCK) -> pd.DataFrame:
        """
        Build monitoring pool by fetching 5-day volume and performance data efficiently.
        Uses yfinance to download all symbols at once for better performance.
        
        Args:
            symbols: List of dictionaries with 'symbol' and 'name' keys from CSV file
            market_type: Market type for cache naming
            
        Returns:
            DataFrame with symbol, name, 5-day avg volume, and performance metrics
        """
        print(f"Building monitoring pool for {len(symbols)} symbols...")
        
        # 基准指数：用于计算相对强度
        BENCHMARK = {
            MarketType.US_STOCK: 'SPY',
            MarketType.ETF: 'SPY',
            MarketType.HK_STOCK: '^HSI',
        }
        benchmark_symbol = BENCHMARK.get(market_type, 'SPY')

        # Extract symbol names and create mapping
        symbol_names = [item['symbol'] for item in symbols]
        formatted_symbols = [format_symbol_name(symbol) for symbol in symbol_names]
        symbol_to_name = {formatted_symbol: item['name'] for formatted_symbol, item in zip(formatted_symbols, symbols)}
        
        # Download all symbols at once using yfinance
        print("Downloading data for all symbols in batch...")
        try:
            hist_data = yf.download(formatted_symbols, period="6mo", interval="1d", auto_adjust=True)
            print(f"Downloaded data for {len(hist_data.columns.levels[1])} symbols")
        except Exception as e:
            print(f"Error downloading batch data: {e}")
            raise e

        # 下载基准指数数据
        benchmark_perf = {}
        try:
            bench_data = yf.download(benchmark_symbol, period="6mo", interval="1d", auto_adjust=True)
            if not bench_data.empty:
                bench_close = bench_data['Close'].squeeze()
                for days in [20, 40, 90, 180]:
                    if len(bench_close) > days:
                        benchmark_perf[days] = float(
                            (bench_close.iloc[-1] - bench_close.iloc[-days-1]) / bench_close.iloc[-days-1] * 100
                        )
                print(f"Benchmark {benchmark_symbol}: 20d={benchmark_perf.get(20,0):.1f}% 90d={benchmark_perf.get(90,0):.1f}%")
        except Exception as e:
            print(f"Warning: benchmark download failed ({e}), relative strength will be 0")
        
        results = []
        successful_symbols = 0
        
        for symbol in formatted_symbols:
            try:
                if symbol not in hist_data.columns.levels[1]:
                    print(f"  No data available for {symbol}")
                    continue
                
                symbol_data = hist_data.xs(symbol, level=1, axis=1)
                
                if symbol_data.empty or len(symbol_data) < 5:
                    print(f"  Insufficient data for {symbol}")
                    continue
                
                # 5日平均成交额
                recent_data = symbol_data.tail(5)
                hlc3 = (recent_data['High'] + recent_data['Low'] + recent_data['Close']) / 3
                volume_5d_avg = (recent_data['Volume'] * hlc3).mean()
                current_price = recent_data['Close'].iloc[-1]
                
                if volume_5d_avg < 1e6:
                    continue
                
                current_price_perf = symbol_data['Close'].iloc[-1]
                performance_20d = 0.0
                performance_40d = 0.0
                performance_90d = 0.0
                performance_180d = 0.0

                if len(symbol_data) >= 20:
                    price_20d_ago = symbol_data['Close'].iloc[-21]
                    performance_20d = float((current_price_perf - price_20d_ago) / price_20d_ago * 100)
                
                if len(symbol_data) >= 40:
                    price_40d_ago = symbol_data['Close'].iloc[-41]
                    performance_40d = float((current_price_perf - price_40d_ago) / price_40d_ago * 100)
                
                if len(symbol_data) >= 90:
                    price_90d_ago = symbol_data['Close'].iloc[-91]
                    performance_90d = float((current_price_perf - price_90d_ago) / price_90d_ago * 100)
                
                if len(symbol_data) >= 180:
                    price_180d_ago = symbol_data['Close'].iloc[-181]
                    performance_180d = float((current_price_perf - price_180d_ago) / price_180d_ago * 100)
                elif len(symbol_data) >= 90:
                    performance_180d = performance_90d

                # === 新增：相对���度（超额收益）===
                rs_20d  = performance_20d  - benchmark_perf.get(20,  0)
                rs_40d  = performance_40d  - benchmark_perf.get(40,  0)
                rs_90d  = performance_90d  - benchmark_perf.get(90,  0)
                rs_180d = performance_180d - benchmark_perf.get(180, 0)

                # === 新增：量价配合分 ===
                # 近20日均量 vs 前20日均量，>1 说明近期放量
                vol_score = 1.0
                if len(symbol_data) >= 40:
                    vol_recent = symbol_data['Volume'].iloc[-20:].mean()
                    vol_prev   = symbol_data['Volume'].iloc[-40:-20].mean()
                    if vol_prev > 0:
                        vol_score = float(vol_recent / vol_prev)

                # === 新增：趋势平滑性（线性回归 R²）===
                # 近20���收盘价对时间的线性回归 R²，越高说明上涨越平稳
                trend_r2 = 0.0
                if len(symbol_data) >= 20:
                    try:
                        closes_20 = symbol_data['Close'].iloc[-20:].values.astype(float)
                        x = np.arange(len(closes_20))
                        # 归一化
                        closes_norm = closes_20 / closes_20[0]
                        coeffs = np.polyfit(x, closes_norm, 1)
                        y_pred = np.polyval(coeffs, x)
                        ss_res = np.sum((closes_norm - y_pred) ** 2)
                        ss_tot = np.sum((closes_norm - closes_norm.mean()) ** 2)
                        trend_r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0
                        trend_r2 = max(0.0, trend_r2)  # clip 负值
                    except Exception:
                        trend_r2 = 0.0

                # === 综合强势评分 ===
                # 权重：相对强度(20d) 40% + 量价配合 30% + 趋势平滑 30%
                # 相对强度归一化到0-1区间（以50%超额为满分）
                rs_score    = min(max(rs_20d / 50.0, 0), 1)
                vol_norm    = min(max((vol_score - 0.5) / 1.5, 0), 1)  # 0.5x-2x → 0-1
                trend_score = trend_r2  # 已经是0-1
                momentum_score = rs_score * 0.4 + vol_norm * 0.3 + trend_score * 0.3

                original_symbol = symbol_names[formatted_symbols.index(symbol)]
                
                result = {
                    'symbol': symbol,
                    'name': symbol_to_name.get(symbol, original_symbol),
                    'volume_5d_avg': volume_5d_avg,
                    'performance_20d': performance_20d,
                    'performance_40d': performance_40d,
                    'performance_90d': performance_90d,
                    'performance_180d': performance_180d,
                    'rs_20d': rs_20d,       # 相对强度（超额收益）
                    'vol_score': vol_score, # 量价配合
                    'trend_r2': trend_r2,   # 趋势平滑性
                    'momentum_score': momentum_score,  # 综合评分
                    'current_price': current_price,
                    'data_points_5d': len(recent_data),
                    'data_points_perf': len(symbol_data)
                }
                
                results.append(result)
                successful_symbols += 1
                
                if successful_symbols % 50 == 0:
                    print(f"  Processed {successful_symbols}/{len(symbols)} symbols...")
                
            except Exception as e:
                print(f"  Error processing {symbol}: {e}")
                continue
        
        df_result = pd.DataFrame(results)
        
        if df_result.empty:
            print("No valid data found for any symbols")
            return pd.DataFrame()
        
        df_result = df_result.sort_values('volume_5d_avg', ascending=False)
        
        # Sort by 5-day average volume in descending order
        df_result = df_result.sort_values('volume_5d_avg', ascending=False)
        
        # Cache the results
        cache_data = {
            'monitoring_pool': df_result.to_dict('records'),
            'timestamp': pd.Timestamp.now().isoformat(),
            'symbol_count': len(df_result),
            'top_volume_count': self.config.top_volume_count,
            'market_type': market_type.value
        }
        
        cache_name = self.config.get_cache_name_for_market(market_type)
        cache_path = Path(self.config.cache_dir) / f"{cache_name}.json"
        cache_path.parent.mkdir(exist_ok=True)
        
        import json
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        
        print(f"Monitoring pool built: {len(df_result)} symbols")
        print(f"Top 5 by volume: {df_result.head()['symbol'].tolist()}")
        print(f"Results cached to: {cache_path}")
        
        return df_result
    
    def _fetch_stock_data(self, symbol: str, timeframe: str, limit: int = 200) -> Optional[pd.DataFrame]:
        """
        Fetch stock data using OpenBB.

        Args:
            symbol: Stock symbol
            timeframe: '1d' for daily, '4h' for 4-hour, '5d' for 5 days
            limit: Number of periods to fetch

        Returns:
            DataFrame with OHLC data or None if failed
        """
        try:
            # Map timeframe to provider
            if timeframe == '5d':
                symbol_hk = format_symbol_name(symbol)
                if str(symbol) == symbol_hk:  # us stock & etf
                    data = obb.equity.price.historical(
                        symbol=symbol,
                        interval='5d',
                        provider='yfinance'
                    )
                else:  # hk stock
                    data = obb.equity.price.historical(
                        symbol=symbol_hk,
                        interval='5d',
                        provider='yfinance',
                        period='6mo'
                    )
            elif timeframe == '1d':
                symbol_hk = format_symbol_name(symbol)
                if str(symbol) == symbol_hk:  # us stock & etf
                    data = obb.equity.price.historical(
                        symbol=symbol,
                        interval='1d',
                        provider='yfinance',
                        limit=limit
                    )
                else:  # hk stock
                    data = obb.equity.price.historical(
                        symbol=symbol_hk,
                        interval='1d',
                        provider='yfinance'
                    )
            elif timeframe == '1h':
                symbol_hk = format_symbol_name(symbol)
                if str(symbol) == symbol_hk:  # us stock & etf
                    data = obb.equity.price.historical(
                        symbol=symbol,
                        interval='1h',
                        provider='yfinance'
                    )
                else:  # hk stock
                    data = obb.equity.price.historical(
                        symbol=symbol_hk,
                        interval='1h',
                        provider='yfinance'
                    )
            elif timeframe == '4h':
                df_1h = self._fetch_stock_data(symbol, '1h', 4 * limit + 24)
                if df_1h is None:
                    return None
                df_4h = DataAggregator.get_4h_data_from_1h(df_1h)
                return df_4h
            elif timeframe == '2h':
                df_1h = self._fetch_stock_data(symbol, '1h', 2 * limit + 12)
                if df_1h is None:
                    return None
                df_2h = DataAggregator.get_2h_data_from_1h(df_1h)
                return df_2h
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

    def _analyze_single_stock(self, symbol: str, name: str, timeframe: str) -> Optional[Dict]:
        """
        Analyze a single stock for low volatility conditions.
        
        Args:
            symbol: Stock symbol
            name: Stock/ETF name
            timeframe: Timeframe to analyze
            
        Returns:
            Analysis results dictionary or None if failed
        """
        print(f"  Analyzing {symbol} on {timeframe}...")
        
        # Fetch data
        df = self._fetch_stock_data(symbol, timeframe, limit=90)
        if df is None or len(df) < 50:  # Need sufficient data
            print(f"    Insufficient data for {symbol}")
            print(df)
            return None
        
        # Extract OHLC arrays
        close_prices = df['close'].values
        high_prices = df['high'].values
        low_prices = df['low'].values
        open_prices = df['open'].values
        
        # Calculate RSI
        rsi_values = self.tech_indicators.calculate_rsi(close_prices, self.config.rsi_period)
        latest_rsi = self.tech_indicators.get_latest_value(rsi_values)
        
        if latest_rsi is None:
            print(f"    Could not calculate RSI for {symbol}")
            return None
        
        # Check for low volatility
        is_low_vol = self.volatility_calc.is_low_volatility(close_prices, high_prices, low_prices)
        
        # Check for breakout signal (for strong trend stocks like MINIMAX)
        is_breakout = self.volatility_calc.is_breakout_signal(close_prices, high_prices, low_prices)
        
        # Generate alert: low volatility OR breakout signal
        alert = self.alert_system.generate_alert(
            symbol=symbol,
            name=name,
            timeframe=timeframe,
            rsi_value=latest_rsi,
            is_low_volatility=(is_low_vol or is_breakout)
        )
        
        result = {
            'symbol': symbol,
            'timeframe': timeframe,
            'rsi': latest_rsi,
            'is_low_volatility': is_low_vol,
            'is_breakout': is_breakout,
            'alert': alert,
            'data_points': len(df)
        }
        
        if alert:
            signal_type = '突破' if (is_breakout and not is_low_vol) else '低波动'
            print(f"    ALERT [{signal_type}]: {alert.format_message()}")
        else:
            print(f"    No alert: RSI={latest_rsi:.1f}, LowVol={is_low_vol}, Breakout={is_breakout}")
        
        return result
    
    def analyze_monitoring_pool(self, timeframe: str, market_type: MarketType = MarketType.US_STOCK) -> Tuple[List[Alert], Dict[str, Dict]]:
        """
        Analyze all stocks in the monitoring pool for a specific timeframe.
        
        Args:
            timeframe: The timeframe to analyze (e.g., '4h', '1d')
            market_type: Market type to analyze
        
        Returns:
            Tuple of (alerts, analysis_results)
        """
        print(f"Getting monitoring pool for timeframe: {timeframe}...")
        
        # Check if we need to build the monitoring pool
        cache_name = self.config.get_cache_name_for_market(market_type)
        if not self.data_loader.is_cache_valid(cache_name):
            print("Cache expired or missing, building new monitoring pool...")
            # Get symbols from CSV
            csv_path = self.config.get_csv_path_for_market(market_type)
            symbols_data = self.data_loader.read_symbol_list_from_csv(csv_path)
            # Build monitoring pool with actual data
            monitoring_pool_df = self.build_monitoring_pool(symbols_data, market_type)
        else:
            print("Using cached monitoring pool data...")
            monitoring_pool_df = self.data_loader.get_monitoring_pool_data(market_type)
        
        if monitoring_pool_df.empty:
            print("No monitoring pool data available")
            return [], {}
        
        # Head performance symbols for analysis
        high_performance_symbols = self.data_loader.get_performance_symbols(market_type)

        print(f"High performance symbols: {high_performance_symbols}")

        # Create symbol to name mapping
        symbol_to_name = dict(zip(monitoring_pool_df['symbol'], monitoring_pool_df['name']))

        all_alerts = []
        analysis_results = {}
        
        # Analyze each symbol on the specified timeframe
        for i, symbol in enumerate(high_performance_symbols):
            print(f"Progress: {i+1}/{len(high_performance_symbols)} - {symbol}")
            
            # Get name from monitoring pool, fallback to symbol if not found
            name = symbol_to_name.get(symbol, symbol)
            
            result = self._analyze_single_stock(symbol, name, timeframe)
            if result:
                analysis_results[symbol] = {timeframe: result}
                if result['alert']:
                    all_alerts.append(result['alert'])
        
        print(f"Analysis complete for {timeframe}. Generated {len(all_alerts)} alerts.")
        return all_alerts, analysis_results
    
    def run_full_analysis(self, timeframe: str, market_type: MarketType = MarketType.US_STOCK, skip_market_conditions: bool = False, dry_run: bool = False) -> Dict:
        """
        Run the complete analysis including market conditions and alerts.
        
        Args:
            timeframe: Timeframe to analyze
            market_type: Market type to analyze
            skip_market_conditions: Skip market condition checks
            dry_run: Run without sending notifications
        
        Returns:
            Complete analysis results
        """
        print("Starting full stock analysis...")
        
        # Setup OpenBB
        self._setup_openbb()
        
        # Check market conditions first
        should_trigger = True
        market_conditions = {}
        if not skip_market_conditions:
            should_trigger = False
            print("Checking market conditions...")
            market_conditions = self.market_checker.check_all_timeframes(market_type)
            should_trigger = self.market_checker.should_trigger_alerts(market_type)
        
        print(f"Market condition check: {'TRIGGER ALERTS' if should_trigger else 'NO ALERTS'}")
        
        # Debug output, to check whether filtered symbols are correct
        if timeframe == "1d":
            high_performance_symbols, high_performance_names, high_performance_performances, high_performance_volumes = self.data_loader.get_performance_symbols_in_detail(market_type)
            if high_performance_symbols:
                # Use markdown table for the alert
                symbol_name = "美股代码" if market_type == MarketType.US_STOCK else ("ETF代码" if market_type == MarketType.ETF else "港股代码")
                alert_text = "监控品种列表：\n"
                
                # Only show name column for HK stocks
                if market_type == MarketType.HK_STOCK:
                    alert_text += f"| {symbol_name} | 名称 | 20天涨幅 | 5日平均 |\n"
                    alert_text += "|:--------|:-----|:---------:|--------:|\n"
                    for symbol, name, performance, volume in zip(high_performance_symbols, high_performance_names, high_performance_performances, high_performance_volumes):
                        if '.HK' in symbol:
                            symbol = symbol.replace('.HK', '')
                        alert_text += f"| {symbol} | {name} | {performance:.1f}% | {volume} |\n"
                else:
                    # US stocks and ETFs don't show name column
                    alert_text += f"| {symbol_name} | 20天涨幅 | 5日平均 |\n"
                    alert_text += "|:--------|:---------:|--------:|\n"
                    for symbol, performance, volume in zip(high_performance_symbols, high_performance_performances, high_performance_volumes):
                        if '.HK' in symbol:
                            symbol = symbol.replace('.HK', '')
                        alert_text += f"| {symbol} | {performance:.1f}% | {volume} |\n"
                
                if not dry_run:
                    self.alert_system.send_wechat_markdown(alert_text)
                else:
                    print(alert_text)

        # Only analyze monitoring pool if market conditions are met
        if should_trigger:
            print("Market conditions met - proceeding with analysis...")
            all_alerts = []
            all_analysis_results = {}
            
            # Analyze each timeframe separately
            # for timeframe in self.config.timeframes:
            print(f"Analyzing timeframe: {timeframe}")
            alerts, analysis_results = self.analyze_monitoring_pool(timeframe, market_type)
            all_alerts.extend(alerts)
            all_analysis_results.update(analysis_results)
            
            filtered_alerts = all_alerts
            analysis_results = all_analysis_results
        else:
            print("Market conditions not met - skipping analysis")
            filtered_alerts = []
            analysis_results = {}
        
        # Send alerts if any
        if filtered_alerts:
            print(f"Sending {len(filtered_alerts)} alerts...")
            if not dry_run:
                send_results = self.alert_system.send_batch_alerts(filtered_alerts)
            else:
                print(f"DRY RUN: Would send {len(filtered_alerts)} alerts")
                send_results = {"success": len(filtered_alerts), "failure": 0}
            print(f"Alert sending results: {send_results}")
        else:
            print("No alerts to send")
        
        # Generate summary
        if not dry_run:
            summary = self.alert_system.format_summary_message(filtered_alerts, market_conditions)
        else:
            print("DRY RUN: Would generate summary")
            summary = "DRY RUN: Summary would be here"
        
        return {
            'market_conditions': market_conditions,
            'should_trigger_alerts': should_trigger,
            'alerts': filtered_alerts,
            'analysis_results': analysis_results,
            'summary': summary,
            'timestamp': pd.Timestamp.now()
        }
    
    def get_analysis_summary(self, results: Dict) -> str:
        """
        Get a formatted summary of the analysis results.
        
        Args:
            results: Results from run_full_analysis()
            
        Returns:
            Formatted summary string
        """
        summary_lines = [
            f"Analysis completed at: {results['timestamp']}",
            f"Market trigger: {'YES' if results['should_trigger_alerts'] else 'NO'}",
            f"Alerts generated: {len(results['alerts'])}",
            f"Symbols analyzed: {len(results['analysis_results'])}",
            "",
            "Market Conditions:"
        ]
        
        for timeframe, (is_bearish, etf_conditions) in results['market_conditions'].items():
            bearish_count = sum(1 for is_bearish in etf_conditions.values() if is_bearish)
            summary_lines.append(f"  {timeframe}: {bearish_count}/{len(etf_conditions)} ETFs bearish")
        
        if results['alerts']:
            summary_lines.extend(["", "Alerts:"])
            for alert in results['alerts']:
                summary_lines.append(f"  {alert.format_message()}")
        
        return "\n".join(summary_lines)
