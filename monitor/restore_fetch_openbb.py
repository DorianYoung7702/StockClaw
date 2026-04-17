# restore_fetch_openbb.py - 恢复 _fetch_stock_data 为 openbb 版本

with open('stock_analyzer.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_method = '''    def _fetch_stock_data(self, symbol: str, timeframe: str, limit: int = 200) -> Optional[pd.DataFrame]:
        """
        Fetch stock data using yfinance directly.

        Args:
            symbol: Stock symbol
            timeframe: '1d' for daily, '4h' for 4-hour, '1h' for 1-hour
            limit: Number of periods to fetch

        Returns:
            DataFrame with OHLC data or None if failed
        """
        try:
            symbol_yf = format_symbol_name(symbol)

            if timeframe == '1d':
                df = yf.Ticker(symbol_yf).history(period='1y', interval='1d')
            elif timeframe == '1h':
                df = yf.Ticker(symbol_yf).history(period='60d', interval='1h')
            elif timeframe == '4h':
                df_1h = self._fetch_stock_data(symbol, '1h', 4 * limit + 24)
                if df_1h is None:
                    return None
                return DataAggregator.get_4h_data_from_1h(df_1h)
            elif timeframe == '2h':
                df_1h = self._fetch_stock_data(symbol, '1h', 2 * limit + 12)
                if df_1h is None:
                    return None
                return DataAggregator.get_2h_data_from_1h(df_1h)
            elif timeframe == '5d':
                df = yf.Ticker(symbol_yf).history(period='6mo', interval='1d')
            else:
                print(f"Unsupported timeframe: {timeframe}")
                return None

            if df is None or df.empty:
                print(f"No data received for {symbol} on {timeframe}")
                return None

            # Normalize column names to lowercase
            df.columns = [c.lower() for c in df.columns]
            # Reset index so date becomes a column
            df = df.reset_index()
            col0 = df.columns[0]
            if col0 != 'date':
                df = df.rename(columns={col0: 'date'})

            return df

        except Exception as e:
            print(f"Error fetching data for {symbol} on {timeframe}: {e}")
            return None'''

new_method = '''    def _fetch_stock_data(self, symbol: str, timeframe: str, limit: int = 200) -> Optional[pd.DataFrame]:
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
            return None'''

if old_method in content:
    content = content.replace(old_method, new_method)
    with open('stock_analyzer.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Done! Restored to openbb version.')
else:
    print('ERROR: old method not found exactly, check whitespace')
