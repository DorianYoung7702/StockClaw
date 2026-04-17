#!/usr/bin/env python3
"""
update_symbol_list.py
每次监控启动时调用，自动从 OpenBB 拉取新上���/高成交额股票，
追加到本地 CSV，防止遗漏新上市标的。

用法：
    from update_symbol_list import update_all_symbol_lists
    update_all_symbol_lists()  # 在 main.py / build_monitoring_pool.py 启动时调用
"""
import logging
import time
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta


def _patch_openbb_core():
    """openbb-core 1.6.7 removed OBBject_* aliases needed by openbb-equity 1.6.1.
    Monkey-patch them back before importing obb."""
    try:
        import openbb_core.app.provider_interface as pi
        from openbb_core.app.provider_interface import OBBject
        for name in [
            "OBBject_EquityInfo", "OBBject_EquityScreener", "OBBject_EquitySearch",
            "OBBject_HistoricalMarketCap", "OBBject_MarketSnapshots",
        ]:
            if not hasattr(pi, name):
                setattr(pi, name, OBBject)
    except Exception:
        pass

logger = logging.getLogger(__name__)

# CSV 路径（相���于项目根目录）
US_CSV = "20251020232140.csv"
HK_CSV = "hk_stocks.csv"

# 成交额阈值（volume * price）
US_MIN_TURNOVER = 1e8   # 美股：1亿 USD
HK_MIN_TURNOVER = 1e8   # 港股：1亿 HKD

# 更新冷却时间（秒），避免频繁触发 yfinance rate limit
UPDATE_COOLDOWN_HOURS = 1
_LOCK_FILE = Path(".universe_update_lock")


def _get_existing_symbols(csv_path: str, symbol_col: str) -> set:
    """读取 CSV 中已有的 symbol 集合。"""
    p = Path(csv_path)
    if not p.exists():
        return set()
    try:
        df = pd.read_csv(csv_path, usecols=[symbol_col])
        return set(df[symbol_col].astype(str).str.strip())
    except Exception as e:
        logger.warning(f"读取 {csv_path} 失败: {e}")
        return set()


def _obb_screener_paged(obb, country: str, volume_min: int, page_size: int = 200,
                        max_retries: int = 5, retry_wait: int = 30) -> pd.DataFrame:
    """分页拉取 OpenBB yfinance screener 全量结果，含限速重试。"""
    all_rows = []
    offset = 0
    while True:
        last_err = None
        for attempt in range(max_retries):
            try:
                result = obb.equity.screener(
                    provider="yfinance",
                    country=country,
                    volume_min=volume_min,
                    limit=page_size,
                    offset=offset,
                )
                if not result or not result.results:
                    return pd.DataFrame(all_rows)
                batch = [r.model_dump() for r in result.results]
                all_rows.extend(batch)
                logger.info(f"[UpdateUniverse]   offset={offset}, got {len(batch)} (total {len(all_rows)})")
                last_err = None
                break
            except Exception as e:
                last_err = e
                wait = retry_wait * (attempt + 1)
                logger.warning(f"[UpdateUniverse] offset={offset} 失败 (attempt {attempt+1}/{max_retries}): {e}")
                logger.info(f"[UpdateUniverse] 等待 {wait}s 后重试...")
                time.sleep(wait)
        if last_err:
            logger.error(f"[UpdateUniverse] offset={offset} 重试耗尽，停止分页")
            break
        if len(batch) < page_size:
            break
        offset += page_size
        time.sleep(1)
    return pd.DataFrame(all_rows)


def update_us_symbols(csv_path: str = US_CSV, min_turnover: float = US_MIN_TURNOVER) -> int:
    """
    从 OpenBB yfinance screener 全量拉取美股，
    覆盖写入 CSV（非追加），保证最新最全。
    返回写入的股票数量。
    """
    _patch_openbb_core()
    try:
        from openbb import obb
    except ImportError:
        logger.error("OpenBB 未安装，跳过美股更新")
        return 0

    logger.info("[UpdateUniverse] 全量拉取美股 screener (yfinance, country=us)...")

    try:
        df = _obb_screener_paged(obb, country="us", volume_min=100_000)
        if df.empty:
            logger.warning("[UpdateUniverse] 美股 screener 返回空")
            return 0

        logger.info(f"[UpdateUniverse] 美股原始 {len(df)} 条")

        # 计算成交额过滤
        price_col = next((c for c in ['price', 'previous_close', 'open'] if c in df.columns), None)
        if price_col and 'volume' in df.columns:
            df['_turnover'] = (
                pd.to_numeric(df['volume'], errors='coerce').fillna(0) *
                pd.to_numeric(df[price_col], errors='coerce').fillna(0)
            )
        else:
            df['_turnover'] = pd.to_numeric(df.get('market_cap', 0), errors='coerce').fillna(0)

        df = df[df['_turnover'] >= min_turnover].copy()
        logger.info(f"[UpdateUniverse] 成交额>{min_turnover/1e8:.0f}亿USD: {len(df)} 只")

        # 覆盖写入（全量最新）
        rows = []
        for i, (_, row) in enumerate(df.iterrows(), 1):
            rows.append({
                'No.': i,
                'Symbol': str(row.get('symbol', '')).upper(),
                'Name': row.get('name', ''),
                'Volume': row.get('volume', 0),
                'Price': row.get(price_col, 0) if price_col else 0,
            })
        out = pd.DataFrame(rows)
        out.to_csv(csv_path, index=False)
        logger.info(f"[UpdateUniverse] 美股 CSV 覆盖写入完成，{len(out)} 只 -> {csv_path}")
        return len(out)

    except Exception as e:
        logger.error(f"[UpdateUniverse] 美股更新失败: {e}", exc_info=True)
        return 0


def update_hk_symbols(csv_path: str = HK_CSV, min_turnover: float = HK_MIN_TURNOVER) -> int:
    """
    从 OpenBB yfinance screener 全量拉取港股，覆盖写入 CSV。
    symbol 格式：openbb 返回 '0700.HK'，CSV 存为 '00700'（5位补零）.
    返回写入的股票数量。
    """
    _patch_openbb_core()
    try:
        from openbb import obb
    except ImportError:
        logger.error("OpenBB 未安装，跳过港股更新")
        return 0

    logger.info("[UpdateUniverse] 全量拉取港股 screener (yfinance, country=hk)...")

    def to_hk_code(sym: str) -> str:
        """'0700.HK' -> '00700'，保持5位补零。"""
        s = str(sym).upper().replace('.HK', '').strip()
        return s.zfill(5) if s.isdigit() else s

    try:
        df = _obb_screener_paged(obb, country="hk", volume_min=50_000)
        if df.empty:
            logger.warning("[UpdateUniverse] 港股 screener 返回空")
            return 0

        logger.info(f"[UpdateUniverse] 港股原始 {len(df)} 条")

        price_col = next((c for c in ['price', 'previous_close', 'open'] if c in df.columns), None)
        if price_col and 'volume' in df.columns:
            df['_turnover'] = (
                pd.to_numeric(df['volume'], errors='coerce').fillna(0) *
                pd.to_numeric(df[price_col], errors='coerce').fillna(0)
            )
        else:
            df['_turnover'] = pd.to_numeric(df.get('market_cap', 0), errors='coerce').fillna(0)

        df = df[df['_turnover'] >= min_turnover].copy()
        logger.info(f"[UpdateUniverse] 成交额>{min_turnover/1e8:.0f}亿HKD: {len(df)} 只")

        rows = []
        for i, (_, row) in enumerate(df.iterrows(), 1):
            rows.append({
                '序号': i,
                '代码': to_hk_code(str(row.get('symbol', ''))),
                '名称': row.get('name', ''),
                '成交量': row.get('volume', 0),
                '最新价': row.get(price_col, 0) if price_col else 0,
            })
        out = pd.DataFrame(rows)
        out.to_csv(csv_path, index=False, encoding='utf-8-sig')
        logger.info(f"[UpdateUniverse] 港股 CSV 覆盖写入完成，{len(out)} 只 -> {csv_path}")
        return len(out)

    except Exception as e:
        logger.error(f"[UpdateUniverse] 港股更新失败: {e}", exc_info=True)
        return 0


def update_all_symbol_lists(
    us_csv: str = US_CSV,
    hk_csv: str = HK_CSV,
    us_min_turnover: float = US_MIN_TURNOVER,
    hk_min_turnover: float = HK_MIN_TURNOVER,
    force: bool = False,
) -> dict:
    """
    主入口：启动时调用，自动更新港股和美股 symbol 列表。
    有冷却机制：距上次更新不足 UPDATE_COOLDOWN_HOURS 小时则跳过，避免 rate limit。
    force=True ���强制更新。
    返回 {'us_added': N, 'hk_added': M}
    """
    logger.info("=" * 50)
    logger.info("[UpdateUniverse] 启动 Symbol 列表更新")
    logger.info(f"[UpdateUniverse] 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)

    # 冷却检查
    if not force and _LOCK_FILE.exists():
        try:
            last_update = datetime.fromisoformat(_LOCK_FILE.read_text().strip())
            elapsed = datetime.now() - last_update
            if elapsed < timedelta(hours=UPDATE_COOLDOWN_HOURS):
                remaining = int((timedelta(hours=UPDATE_COOLDOWN_HOURS) - elapsed).total_seconds() / 60)
                logger.info(f"[UpdateUniverse] 距上次更新仅 {int(elapsed.total_seconds()/60)} 分钟，冷却中（剩余 {remaining} 分钟），跳过本次更新")
                return {'us_added': 0, 'hk_added': 0}
        except Exception:
            pass

    us_added = update_us_symbols(us_csv, us_min_turnover)
    time.sleep(2)  # 两次请求之间间隔，避免连续触发 rate limit
    hk_added = update_hk_symbols(hk_csv, hk_min_turnover)

    # 写入更新时间戳
    try:
        _LOCK_FILE.write_text(datetime.now().isoformat())
    except Exception:
        pass

    logger.info(f"[UpdateUniverse] 完成：美股新增 {us_added} 只，港股新增 {hk_added} 只")
    return {'us_added': us_added, 'hk_added': hk_added}


# ---------------------------------------------------------------------------
# FMP provider 实现（需要 FMP_API_KEY 环境变量）
# ---------------------------------------------------------------------------

def update_us_symbols_fmp(csv_path: str = US_CSV, min_turnover: float = US_MIN_TURNOVER) -> int:
    """
    从公开数据源拉取全量美股，无需 API Key，覆盖写入 CSV。
    数据源优先级：
      1. NASDAQ Trader FTP（nasdaqlisted + otherlisted，全量 ~1万只）
      2. SEC EDGAR company_tickers（全量上市公司，备用）
      3. 热门种子兜底
    """
    import requests, io
    logger.info("[Public] 全量拉取美股 (NASDAQ Trader FTP + SEC EDGAR)...")

    symbols: dict[str, str] = {}  # symbol -> name
    HDR = {"User-Agent": "AtlasAgent/1.0 contact@example.com"}

    def _fetch_nasdaq_ftp(path: str) -> pd.DataFrame | None:
        """尝试 HTTP 和 HTTPS 两种方式访问 NASDAQ FTP。"""
        for scheme in ("http", "https"):
            try:
                url = f"{scheme}://ftp.nasdaqtrader.com{path}"
                resp = requests.get(url, timeout=20, headers=HDR)
                resp.raise_for_status()
                return pd.read_csv(io.StringIO(resp.text), sep="|")
            except Exception as e:
                logger.debug(f"[Public] {scheme} {path} 失败: {e}")
        return None

    # 1. NASDAQ 上市股票（含 ETF 过滤列）
    df = _fetch_nasdaq_ftp("/symboldirectory/nasdaqlisted.txt")
    if df is not None:
        sym_col  = next((c for c in df.columns if c.strip() == "Symbol"), None)
        name_col = next((c for c in df.columns if "Security" in c or "Name" in c), None)
        etf_col  = next((c for c in df.columns if c.strip() == "ETF"), None)
        if sym_col:
            for _, r in df.iterrows():
                sym = str(r[sym_col]).strip()
                if not sym or sym.startswith("File") or "$" in sym or len(sym) > 5:
                    continue
                if etf_col and str(r[etf_col]).strip().upper() == "Y":
                    continue  # 跳过 ETF
                name = str(r[name_col]).strip() if name_col else sym
                symbols[sym] = name
        logger.info(f"[Public] NASDAQ listed (股票): {len(symbols)} 只")
    else:
        logger.warning("[Public] NASDAQ listed 不可用，跳过")

    prev = len(symbols)
    # 2. 其他交易所（NYSE / AMEX / ARCA）
    df2 = _fetch_nasdaq_ftp("/symboldirectory/otherlisted.txt")
    if df2 is not None:
        sym_col  = next((c for c in df2.columns if "ACT Symbol" in c or c.strip() == "Symbol"), None)
        name_col = next((c for c in df2.columns if "Security" in c or "Name" in c), None)
        etf_col  = next((c for c in df2.columns if c.strip() == "ETF"), None)
        exch_col = next((c for c in df2.columns if "Exchange" in c), None)
        if sym_col:
            for _, r in df2.iterrows():
                sym = str(r[sym_col]).strip()
                if not sym or sym.startswith("File") or "$" in sym or "^" in sym or len(sym) > 5:
                    continue
                if etf_col and str(r[etf_col]).strip().upper() == "Y":
                    continue  # 跳过 ETF
                # 跳过 OTC（Exchange 为空或 U）
                if exch_col and str(r[exch_col]).strip().upper() in ("", "U", "OTC"):
                    continue
                name = str(r[name_col]).strip() if name_col else sym
                if sym not in symbols:
                    symbols[sym] = name
        logger.info(f"[Public] Other listed 后共: {len(symbols)} 只 (+{len(symbols)-prev})")
    else:
        logger.warning("[Public] Other listed 不可用，跳过")

    # 3. SEC EDGAR 备用（兜底补充）
    if len(symbols) < 100:
        try:
            url = "https://www.sec.gov/files/company_tickers.json"
            resp = requests.get(url, timeout=20, headers=HDR)
            resp.raise_for_status()
            data = resp.json()
            for item in data.values():
                sym = str(item.get("ticker", "")).strip().upper()
                name = str(item.get("title", sym))
                if sym and sym not in symbols:
                    symbols[sym] = name
            logger.info(f"[Public] SEC EDGAR 补充后共: {len(symbols)} 只")
        except Exception as e:
            logger.warning(f"[Public] SEC EDGAR 失败: {e}")

    # 4. 热门种子兜底
    EXTRA_US = [
        "NVDA","TSLA","META","AMZN","GOOGL","MSFT","AAPL","AMD","AVGO","ARM",
        "PLTR","MSTR","COIN","CRWD","PANW","DDOG","NET","ZS","SNOW","MDB",
        "SMCI","MRVL","BABA","JD","PDD","BIDU","FUTU","NIO","XPEV","LI",
        "XOM","CVX","COP","SLB","OXY","DVN","PSX","VLO","MPC","FANG",
        "SPY","QQQ","IWM","DIA","SOXL","TQQQ","SQQQ","ARKK","IBIT","SOXS",
    ]
    for sym in EXTRA_US:
        if sym not in symbols:
            symbols[sym] = sym

    if not symbols:
        logger.error("[Public] 未能拉取任何美股数据")
        return 0

    rows = [{"No.": i, "Symbol": sym, "Name": name, "Volume": 0, "Price": 0}
            for i, (sym, name) in enumerate(symbols.items(), 1)]
    out = pd.DataFrame(rows)
    out.to_csv(csv_path, index=False)
    logger.info(f"[Public] 美股 CSV 写入完成，{len(out)} 只 -> {csv_path}")
    return len(out)


def update_hk_symbols_fmp(csv_path: str = HK_CSV, min_turnover: float = HK_MIN_TURNOVER) -> int:
    """
    从 HKEX 官方公开数据拉取全量港股列表，覆盖写入 CSV。
    无需 API Key，数据源：HKEX 官方 Excel。
    """
    import requests, io
    logger.info("[Public] 全量拉取港股 (HKEX 官方列表)...")

    def to_hk_code(sym) -> str:
        s = str(sym).strip().split('.')[0]  # 取数字部分
        return s.zfill(5) if s.isdigit() else s

    try:
        # HKEX 公开的全量上市公司列表 Excel
        hkex_url = (
            "https://www.hkex.com.hk/eng/services/trading/securities/"
            "securitieslists/ListOfSecurities.xlsx"
        )
        logger.info(f"[Public] 下载 HKEX Excel: {hkex_url}")
        resp = requests.get(hkex_url, timeout=30,
                            headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        df = pd.read_excel(io.BytesIO(resp.content), header=2)  # 前2行是标题
        logger.info(f"[Public] HKEX Excel 返回 {len(df)} 条，列: {list(df.columns[:6])}")

        # HKEX Excel 列名：'Stock Code', 'Name of Securities', 'Category', ...
        code_col = next((c for c in df.columns if 'code' in str(c).lower() or '代码' in str(c)), None)
        name_col = next((c for c in df.columns if 'name' in str(c).lower() or '名称' in str(c)), None)
        cat_col  = next((c for c in df.columns if 'categ' in str(c).lower() or 'type' in str(c).lower()), None)

        if code_col is None:
            logger.error(f"[Public] 找不到代码列，实际列名: {list(df.columns)}")
            return 0

        # 过滤：只要普通股/H股（排除权证/布 ETF 等）
        if cat_col:
            keep = df[cat_col].astype(str).str.contains(
                r'Equity|Share|H Share|Red Chip|Stock|GEM', case=False, na=False
            )
            df = df[keep]

        rows = []
        for i, (_, row) in enumerate(df.iterrows(), 1):
            code = to_hk_code(row[code_col])
            name = str(row[name_col]).strip() if name_col else code
            if not code or not code.isdigit():
                continue
            rows.append({
                '序号': i, '代码': code, '名称': name, '成交量': 0, '最新价': 0,
            })

        if not rows:
            logger.error("[Public] 港股数据解析结果为空")
            return 0

        out = pd.DataFrame(rows)
        out.to_csv(csv_path, index=False, encoding='utf-8-sig')
        logger.info(f"[Public] 港股 CSV 写入完成，{len(out)} 只 -> {csv_path}")
        return len(out)

    except Exception as e:
        logger.error(f"[Public] 港股更新失败: {e}", exc_info=True)
        return 0


if __name__ == "__main__":
    import sys
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    parser = argparse.ArgumentParser(description="更新港美股 symbol 列表")
    parser.add_argument('--market', choices=['us', 'hk', 'all'], default='all',
                        help='更新哪个市场 (默认: all)')
    parser.add_argument('--provider', choices=['yfinance', 'fmp'], default='yfinance',
                        help='数据 provider: yfinance (默认) 或 fmp (需要 FMP_API_KEY)')
    parser.add_argument('--us-csv', default=US_CSV, help='美股 CSV 路径')
    parser.add_argument('--hk-csv', default=HK_CSV, help='港股 CSV 路径')
    parser.add_argument('--us-min-turnover', type=float, default=US_MIN_TURNOVER,
                        help='美股最低成交额过滤（默认1亿USD）')
    parser.add_argument('--hk-min-turnover', type=float, default=HK_MIN_TURNOVER,
                        help='港股最低成交额过滤（默认1亿HKD）')
    parser.add_argument('--force', action='store_true',
                        help='强制更新，忽略冷却时间')
    args = parser.parse_args()

    # FMP provider 路径
    if args.provider == 'fmp':
        import os
        from dotenv import load_dotenv
        load_dotenv('env')
        if args.market == 'us':
            n = update_us_symbols_fmp(args.us_csv, args.us_min_turnover)
        elif args.market == 'hk':
            n = update_hk_symbols_fmp(args.hk_csv, args.hk_min_turnover)
        else:
            n = update_us_symbols_fmp(args.us_csv, args.us_min_turnover)
            time.sleep(2)
            n += update_hk_symbols_fmp(args.hk_csv, args.hk_min_turnover)
        import sys; sys.exit(0 if n >= 0 else 1)

    # yfinance provider 路径（原有逻辑）
    if args.market == 'us':
        n = update_us_symbols(args.us_csv, args.us_min_turnover)
    elif args.market == 'hk':
        n = update_hk_symbols(args.hk_csv, args.hk_min_turnover)
    else:
        result = update_all_symbol_lists(
            args.us_csv, args.hk_csv,
            args.us_min_turnover, args.hk_min_turnover,
            force=args.force,
        )
        n = result['us_added'] + result['hk_added']

    sys.exit(0 if n >= 0 else 1)
