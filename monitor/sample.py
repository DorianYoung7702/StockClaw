from openbb import obb


data = obb.equity.price.historical(
    symbol='1810.HK',
    interval='1h',
    provider='yfinance'
)
