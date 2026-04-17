import re

with open('stock_analyzer.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_method_start = '    def _fetch_stock_data(self, symbol: str, timeframe: str, limit: int = 200) -> Optional[pd.DataFrame]:'
old_method_end = '        except Exception as e:\n            print(f"Error fetching data for {symbol} on {timeframe}: {e}")\n            return None\n    \n    def _analyze_single_stock'

new_method = '''    def _fetch_stock_data(self, symbol: str, timeframe: str, limit: int = 200) -> Optional[pd.DataFrame]:
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
            return None

    def _analyze_single_stock'''

# Find the old block
start_idx = content.find(old_method_start)
end_marker = '        except Exception as e:\n            print(f"Error fetching data for {symbol} on {timeframe}: {e}")\n            return None'
end_idx = content.find(end_marker, start_idx)
if end_idx == -1:
    print('ERROR: could not find end marker')
else:
    end_idx += len(end_marker) + 1  # include the newline
    # find next method
    next_method = content.find('    def _analyze_single_stock', end_idx - 5)
    old_block = content[start_idx:next_method]
    new_content = content[:start_idx] + new_method
    # append everything after old block
    new_content += content[next_method + len('    def _analyze_single_stock'):]
    with open('stock_analyzer.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Done! Method replaced successfully.')
