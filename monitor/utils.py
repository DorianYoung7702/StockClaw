



def format_symbol_name(symbol: str | int) -> str:
    """
    If symbol is like "01810" (all digits, or int), format to "1810.HK" (remove left zeros and add postfix).
    Else, return as-is.
    """
    # Convert to string for digit check, but keep original for return as needed
    symbol_str = str(symbol)
    # Check if symbol consists of all digits (from str or int input)
    if symbol_str.isdigit():
        symbol_no_zeros = symbol_str.lstrip('0') or '0'
        # yfinance 港股需要 4 位数字，如 0700.HK
        symbol_padded = symbol_no_zeros.zfill(4)
        return f"{symbol_padded}.HK"
    else:
        return symbol_str





