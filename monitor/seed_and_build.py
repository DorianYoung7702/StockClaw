#!/usr/bin/env python3
"""
seed_and_build.py
一键生成港美股 CSV 符号列表 + 构建监控池缓存。
无需 OpenBB SDK，仅依赖 yfinance + pandas。

用法：
    python seed_and_build.py                  # 构建美股 + 港股
    python seed_and_build.py --market us      # 仅美股
    python seed_and_build.py --market hk      # 仅港股
"""
import argparse
import logging
import sys
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
US_CSV = "20251020232140.csv"
HK_CSV = "hk_stocks.csv"
ETF_CSV = "etf.csv"
CACHE_DIR = Path("cache")

# 美股种子：S&P 500 大市值 + 热门科技/消费/金融/医疗/能源
US_SEEDS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK-B", "AVGO", "JPM",
    "LLY", "V", "UNH", "XOM", "MA", "COST", "HD", "PG", "JNJ", "ABBV",
    "WMT", "NFLX", "CRM", "BAC", "ORCL", "CVX", "MRK", "KO", "PEP", "AMD",
    "ADBE", "TMO", "ACN", "LIN", "MCD", "CSCO", "ABT", "WFC", "PM", "IBM",
    "ISRG", "MS", "DHR", "GE", "NOW", "CAT", "QCOM", "VZ", "AMAT", "INTU",
    "TXN", "LOW", "SPGI", "PFE", "RTX", "AXP", "NEE", "HON", "UNP", "BKNG",
    "BA", "T", "UBER", "GS", "DE", "BLK", "SYK", "GILD", "MDLZ", "SCHW",
    "MMC", "ADI", "LRCX", "REGN", "AMT", "CB", "PLD", "VRTX", "CI", "PANW",
    "BSX", "SNPS", "FI", "KLAC", "CME", "SO", "ICE", "MU", "DUK", "CL",
    "PYPL", "APH", "MCO", "ZTS", "SHW", "TT", "CRWD", "ABNB", "CMG", "PH",
    "USB", "AON", "MSI", "CDNS", "HCA", "WELL", "ITW", "MAR", "ORLY", "EMR",
    "APD", "ECL", "GD", "NOC", "ADP", "PSX", "VLO", "MPC", "EOG", "COP",
    "SLB", "OXY", "FANG", "HES", "DVN", "COIN", "MSTR", "PLTR", "SMCI", "ARM",
    "MRVL", "ON", "DDOG", "NET", "ZS", "SNOW", "MDB", "SHOP", "SQ", "RBLX",
    "DASH", "HOOD", "SOFI", "RIVN", "LCID", "NIO", "XPEV", "LI", "BABA", "JD",
    "PDD", "BIDU", "BILI", "TME", "WB", "ZH", "IQ", "FUTU", "MNSO", "GDS",
]

# 港股种子：恒生指数 + 恒科 + 热门中概 / 红筹
HK_SEEDS = [
    "00700", "09988", "03690", "01810", "09618", "01024", "00941", "02318", "00388", "00005",
    "00939", "01398", "03968", "03988", "01288", "02628", "01299", "02388", "06862", "00011",
    "02269", "01177", "00883", "00857", "00386", "01088", "02899", "00002", "00003", "00006",
    "00012", "00016", "00017", "00019", "00027", "00066", "00101", "00175", "00241", "00267",
    "00288", "00291", "00316", "00322", "00669", "00688", "00728", "00762", "00772", "00823",
    "00868", "00881", "00909", "00916", "00960", "00968", "00981", "00992", "01038", "01044",
    "01109", "01113", "01211", "01378", "01929", "01997", "02007", "02013", "02015", "02018",
    "02020", "02057", "02196", "02313", "02331", "02333", "02382", "02688", "02800", "03323",
    "03328", "03333", "03888", "03993", "06060", "06098", "06160", "06185", "06618", "06690",
    "06969", "09626", "09633", "09668", "09888", "09896", "09901", "09961", "09999", "09698",
]

# ETF 种子
ETF_SEEDS = [
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "EEM", "EFA", "GLD", "SLV",
    "TLT", "HYG", "LQD", "XLF", "XLK", "XLE", "XLV", "XLI", "XLP", "XLY",
    "XLU", "XLB", "XLRE", "XLC", "ARKK", "ARKW", "SOXX", "SMH", "KWEB", "FXI",
    "IBIT", "FBTC", "MCHI", "VGK", "VWO", "INDA", "EWJ", "EWZ", "AAXJ", "SOXL",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. 生成 CSV
# ---------------------------------------------------------------------------

def _batch_snapshot(symbols: list[str]) -> dict[str, tuple[float, int]]:
    """用 yf.download 批量取最近收盘价和成交量，返回 {symbol: (price, volume)}。"""
    result = {}
    try:
        data = yf.download(symbols, period="5d", interval="1d", auto_adjust=True, threads=True)
        if data.empty:
            return result
        for sym in symbols:
            try:
                if len(symbols) == 1:
                    price = float(data["Close"].iloc[-1])
                    vol = int(data["Volume"].iloc[-1])
                else:
                    price = float(data["Close"][sym].iloc[-1])
                    vol = int(data["Volume"][sym].iloc[-1])
                result[sym] = (round(price, 2), vol)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[Seed] batch download failed: {e}")
    return result


def seed_us_csv(csv_path: str = US_CSV):
    """用 yfinance 批量获取美股快照，生成 CSV。"""
    p = Path(csv_path)
    if p.exists():
        logger.info(f"[Seed] 美股 CSV 已存在 ({p})，跳过生成")
        return
    logger.info(f"[Seed] 正在生成美股 CSV: {len(US_SEEDS)} 只 ...")
    snap = _batch_snapshot(US_SEEDS)
    rows = []
    for i, sym in enumerate(US_SEEDS, 1):
        price, vol = snap.get(sym, (0, 0))
        rows.append({"No.": i, "Symbol": sym, "Name": sym, "Volume": vol, "Price": price})
    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False)
    logger.info(f"[Seed] 美股 CSV 写入完成: {len(df)} 只 -> {csv_path}")


def seed_hk_csv(csv_path: str = HK_CSV):
    """用 yfinance 批量获取港股快照，生成 CSV。"""
    p = Path(csv_path)
    if p.exists():
        logger.info(f"[Seed] 港股 CSV 已存在 ({p})，跳过生成")
        return
    logger.info(f"[Seed] 正在生成港股 CSV: {len(HK_SEEDS)} 只 ...")
    yf_syms = [f"{s.lstrip('0')}.HK" for s in HK_SEEDS]
    snap = _batch_snapshot(yf_syms)
    rows = []
    for i, (code, yf_sym) in enumerate(zip(HK_SEEDS, yf_syms), 1):
        price, vol = snap.get(yf_sym, (0, 0))
        rows.append({"序号": i, "代码": code, "名称": code, "成交量": vol, "最新价": price})
    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    logger.info(f"[Seed] 港股 CSV 写入完成: {len(df)} 只 -> {csv_path}")


def seed_etf_csv(csv_path: str = ETF_CSV):
    """生成 ETF CSV。"""
    p = Path(csv_path)
    if p.exists():
        logger.info(f"[Seed] ETF CSV 已存在 ({p})，跳过生成")
        return
    logger.info(f"[Seed] 正在生成 ETF CSV: {len(ETF_SEEDS)} 只 ...")
    snap = _batch_snapshot(ETF_SEEDS)
    rows = []
    for i, sym in enumerate(ETF_SEEDS, 1):
        price, vol = snap.get(sym, (0, 0))
        rows.append({"No.": i, "Symbol": sym, "Name": sym, "Volume": vol, "Price": price})
    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False)
    logger.info(f"[Seed] ETF CSV 写入完成: {len(df)} 只 -> {csv_path}")


# ---------------------------------------------------------------------------
# 2. 构建监控池（复用 stock_analyzer.build_monitoring_pool）
# ---------------------------------------------------------------------------

def build_pool(market_type_str: str, top_n: int = 0):
    """
    构建监控池并写入缓存。
    内联核心逻辑，避免导入 stock_analyzer（其模块级 `from openbb import obb` 未安装）。
    """
    from config import Config, MarketType
    from data_loader import DataLoader
    from utils import format_symbol_name

    mt = MarketType(market_type_str)
    cfg = Config()
    loader = DataLoader(cfg)

    csv_path = cfg.get_csv_path_for_market(mt)
    if not Path(csv_path).exists():
        logger.error(f"[Build] CSV 不存在: {csv_path}")
        return

    symbols_data = loader.read_symbol_list_from_csv(csv_path)

    # 修正：pandas 可能将纯数字代码读为 float (e.g. 1810.0)，需转为干净字符串
    for item in symbols_data:
        s = str(item["symbol"])
        if s.endswith(".0"):
            s = s[:-2]
        item["symbol"] = s

    logger.info(f"[Build] {market_type_str}: 读取 {len(symbols_data)} 只符号，开始构建...")

    # top_n 过滤：若 CSV 无成交量则先下 5d 快照排序
    if top_n > 0 and top_n < len(symbols_data):
        from utils import format_symbol_name as _fmt
        # 检查 CSV 是否有有效成交量
        weights = [float(item.get("weight", 0) or 0) for item in symbols_data]
        if max(weights) == 0:
            logger.info(f"[Build] CSV 无成交量，下载 5d 快照为 {len(symbols_data)} 只排序...")
            snap_syms = [_fmt(item["symbol"]) for item in symbols_data]
            SNAP_CHUNK = 500
            snap_vols: dict[str, float] = {}
            for si in range(0, len(snap_syms), SNAP_CHUNK):
                batch = snap_syms[si:si + SNAP_CHUNK]
                try:
                    sd = yf.download(batch, period="5d", interval="1d",
                                     auto_adjust=True, progress=False, threads=False)
                    if not sd.empty:
                        close = sd["Close"] if isinstance(sd.columns, pd.Index) else sd["Close"]
                        vol   = sd["Volume"] if isinstance(sd.columns, pd.Index) else sd["Volume"]
                        for sym in batch:
                            try:
                                c = float(close[sym].dropna().iloc[-1]) if len(batch) > 1 else float(close.dropna().iloc[-1])
                                v = float(vol[sym].dropna().iloc[-1])   if len(batch) > 1 else float(vol.dropna().iloc[-1])
                                snap_vols[sym] = c * v
                            except Exception:
                                snap_vols[sym] = 0.0
                except Exception as e:
                    logger.warning(f"[Build] 快照批次失败: {e}")
                time.sleep(3)
            symbols_data = sorted(symbols_data, key=lambda x: snap_vols.get(_fmt(x["symbol"]), 0), reverse=True)
            logger.info(f"[Build] 快照排序完成，取前 {top_n} 只")
        symbols_data = symbols_data[:top_n]
        logger.info(f"[Build] top_n={top_n}，实际构建 {len(symbols_data)} 只")

    # --- 核心：与 StockAnalyzer.build_monitoring_pool 等价 ---
    BENCHMARK = {"us_stock": "SPY", "etf": "SPY", "hk_stock": "^HSI"}
    benchmark_symbol = BENCHMARK.get(market_type_str, "SPY")

    symbol_names = [item["symbol"] for item in symbols_data]
    formatted_symbols = [format_symbol_name(s) for s in symbol_names]
    sym2name = {fs: item["name"] for fs, item in zip(formatted_symbols, symbols_data)}

    CHUNK = 100          # 每批 100 只
    DELAY = 15           # 批次间隔（秒）
    MAX_RETRY = 4        # 空批次最大重试次数
    RETRY_WAIT = 90      # 空批次首次等待（秒），指数增长
    MIN_HIT_RATE = 0.15  # 批次命中率低于此视为限速
    total_batches = (len(formatted_symbols) + CHUNK - 1) // CHUNK
    logger.info(f"[Build] 下载 {len(formatted_symbols)} 只行情（{total_batches} 批，每批 {CHUNK} 只，间隔 {DELAY}s）...")

    def _count_valid_symbols(df: "pd.DataFrame", batch: list) -> int:
        """返回 DataFrame 中实际有数据的 symbol 数量。"""
        if df.empty:
            return 0
        if isinstance(df.columns, pd.MultiIndex):
            close = df.get("Close", df.get("close", pd.DataFrame()))
            if isinstance(close, pd.DataFrame):
                return int(close.dropna(how="all", axis=1).shape[1])
            return 1
        # 单只时列是普通 Index
        return 1 if not df.dropna(how="all").empty else 0

    def _download_individually(syms: list, period: str = "6mo") -> "pd.DataFrame":
        """逐只下载，每只间隔 1.5s，失败跳过，合并返回。"""
        parts = []
        for sym in syms:
            try:
                df = yf.download(sym, period=period, interval="1d",
                                 auto_adjust=True, progress=False, threads=False)
                if not df.empty:
                    # 给单只 df 加上 symbol 层，保持 MultiIndex 格式一致
                    df.columns = pd.MultiIndex.from_product([df.columns, [sym]])
                    parts.append(df)
            except Exception as e:
                logger.debug(f"[Build] {sym} 单独下载失败: {e}")
            time.sleep(1.5)
        if not parts:
            return pd.DataFrame()
        merged = pd.concat(parts, axis=1)
        return merged.loc[:, ~merged.columns.duplicated()]

    chunks_data = []
    for i in range(0, len(formatted_symbols), CHUNK):
        batch = formatted_symbols[i:i + CHUNK]
        batch_no = i // CHUNK + 1
        got_data = False

        for attempt in range(MAX_RETRY):
            try:
                chunk_df = yf.download(batch, period="6mo", interval="1d",
                                       auto_adjust=True, progress=False, threads=False)
            except Exception as e:
                logger.warning(f"[Build] 批次 {batch_no} 抛异常: {e}")
                chunk_df = pd.DataFrame()

            valid = _count_valid_symbols(chunk_df, batch)
            hit_rate = valid / len(batch)
            logger.info(f"[Build] 批次 {batch_no} 第{attempt+1}次: {valid}/{len(batch)} 只有数据 (命中率 {hit_rate:.0%})")

            if hit_rate >= MIN_HIT_RATE:
                chunks_data.append(chunk_df)
                got_data = True
                break

            # 命中率太低 → 限速，等待后重试
            if attempt < MAX_RETRY - 1:
                wait = RETRY_WAIT * (2 ** attempt)  # 90 / 180 / 360s
                logger.warning(f"[Build] 批次 {batch_no} 命中率低（限速），等待 {wait}s 后重试...")
                time.sleep(wait)

        if not got_data:
            # 批量全部失败 → 逐只下载兜底
            logger.warning(f"[Build] 批次 {batch_no} 批量失败，改为逐只下载 {len(batch)} 只（约 {len(batch)*1.5:.0f}s）...")
            fallback_df = _download_individually(batch)
            if not fallback_df.empty:
                chunks_data.append(fallback_df)
                logger.info(f"[Build] 批次 {batch_no} 逐只兜底完成")
            else:
                logger.warning(f"[Build] 批次 {batch_no} 彻底放弃")

        if i + CHUNK < len(formatted_symbols):
            logger.info(f"[Build] 批次 {batch_no}/{total_batches} 完成，等待 {DELAY}s...")
            time.sleep(DELAY)

    if not chunks_data:
        logger.error("[Build] yfinance 全部批次返回空")
        return

    if len(chunks_data) == 1:
        hist_data = chunks_data[0]
    else:
        hist_data = pd.concat(chunks_data, axis=1)
        hist_data = hist_data.loc[:, ~hist_data.columns.duplicated()]

    if hist_data.empty:
        logger.error("[Build] yfinance 返回空")
        return

    # 基准
    benchmark_perf: dict[int, float] = {}
    try:
        bench = yf.download(benchmark_symbol, period="6mo", interval="1d", auto_adjust=True)
        if not bench.empty:
            bc = bench["Close"].squeeze()
            for d in [20, 40, 90, 180]:
                if len(bc) > d:
                    benchmark_perf[d] = float((bc.iloc[-1] - bc.iloc[-d - 1]) / bc.iloc[-d - 1] * 100)
            logger.info(f"[Build] Benchmark {benchmark_symbol}: 20d={benchmark_perf.get(20,0):.1f}%")
    except Exception as e:
        logger.warning(f"[Build] Benchmark 下载失败: {e}")

    results = []
    ok = 0
    for symbol in formatted_symbols:
        try:
            if symbol not in hist_data.columns.levels[1]:
                continue
            sd = hist_data.xs(symbol, level=1, axis=1)
            if sd.empty or len(sd) < 5:
                continue

            recent = sd.tail(5)
            hlc3 = (recent["High"] + recent["Low"] + recent["Close"]) / 3
            vol5 = (recent["Volume"] * hlc3).mean()
            cur_price = recent["Close"].iloc[-1]
            if vol5 < 1e6:
                continue

            cp = sd["Close"].iloc[-1]
            perfs = {}
            for d in [20, 40, 90, 180]:
                if len(sd) >= d:
                    perfs[d] = float((cp - sd["Close"].iloc[-d - 1]) / sd["Close"].iloc[-d - 1] * 100)
                else:
                    perfs[d] = perfs.get(90, 0.0) if d == 180 else 0.0

            rs_20 = perfs[20] - benchmark_perf.get(20, 0)

            vol_score = 1.0
            if len(sd) >= 40:
                vr = sd["Volume"].iloc[-20:].mean()
                vp = sd["Volume"].iloc[-40:-20].mean()
                if vp > 0:
                    vol_score = float(vr / vp)

            trend_r2 = 0.0
            if len(sd) >= 20:
                try:
                    c20 = sd["Close"].iloc[-20:].values.astype(float)
                    x = np.arange(len(c20))
                    cn = c20 / c20[0]
                    coeffs = np.polyfit(x, cn, 1)
                    yp = np.polyval(coeffs, x)
                    ss_res = np.sum((cn - yp) ** 2)
                    ss_tot = np.sum((cn - cn.mean()) ** 2)
                    trend_r2 = max(0.0, float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0)
                except Exception:
                    pass

            rs_score = min(max(rs_20 / 50.0, 0), 1)
            vol_norm = min(max((vol_score - 0.5) / 1.5, 0), 1)
            momentum = rs_score * 0.4 + vol_norm * 0.3 + trend_r2 * 0.3

            orig = symbol_names[formatted_symbols.index(symbol)]
            results.append({
                "symbol": symbol,
                "name": sym2name.get(symbol, orig),
                "volume_5d_avg": vol5,
                "current_price": cur_price,
                "performance_20d": perfs[20],
                "performance_40d": perfs[40],
                "performance_90d": perfs[90],
                "performance_180d": perfs[180],
                "rs_20d": rs_20,
                "vol_score": vol_score,
                "trend_r2": trend_r2,
                "momentum_score": momentum,
            })
            ok += 1
            if ok % 50 == 0:
                logger.info(f"  已处理 {ok}/{len(symbols_data)} ...")
        except Exception as e:
            logger.debug(f"  {symbol}: {e}")
            continue

    df = pd.DataFrame(results)
    if df.empty:
        logger.error("[Build] 无有效数据")
        return

    df = df.sort_values("volume_5d_avg", ascending=False)

    # 写缓存
    cache_data = {
        "monitoring_pool": df.to_dict("records"),
        "timestamp": pd.Timestamp.now().isoformat(),
        "symbol_count": len(df),
        "top_volume_count": cfg.top_volume_count,
        "market_type": market_type_str,
    }
    cache_name = cfg.get_cache_name_for_market(mt)
    cache_path = CACHE_DIR / f"{cache_name}.json"
    cache_path.parent.mkdir(exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)

    logger.info(f"[Build] {market_type_str}: 完成！{len(df)} 只有效标的，缓存 -> {cache_path}")
    logger.info(f"[Build] Top 5: {df.head()['symbol'].tolist()}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="种子 CSV + 构建港美股监控池缓存")
    parser.add_argument("--market", choices=["us", "hk", "etf", "all"], default="all")
    parser.add_argument("--seed-only", action="store_true", help="仅生成 CSV，不构建缓存")
    parser.add_argument("--build-only", action="store_true", help="仅构建缓存（CSV 须已存在）")
    parser.add_argument("--top-n", type=int, default=0,
                        help="只取 CSV 前 N 只构建（0=全量）。CSV 无成交量时按快照成交额排序")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    markets = {
        "us": ("us_stock", seed_us_csv, US_CSV),
        "hk": ("hk_stock", seed_hk_csv, HK_CSV),
        "etf": ("etf", seed_etf_csv, ETF_CSV),
    }
    targets = list(markets.keys()) if args.market == "all" else [args.market]

    # Step 1: Seed CSVs
    if not args.build_only:
        for t in targets:
            mt_str, seed_fn, csv = markets[t]
            seed_fn(csv)
            time.sleep(1)

    # Step 2: Build monitoring pools
    if not args.seed_only:
        CACHE_DIR.mkdir(exist_ok=True)
        for t in targets:
            mt_str, _, csv_path = markets[t]
            logger.info(f"\n{'='*60}")
            logger.info(f"[Build] 开始构建 {mt_str} 监控池...")
            logger.info(f"{'='*60}")
            build_pool(mt_str, top_n=args.top_n)
            time.sleep(2)

    logger.info("\n✅ 全部完成！缓存文件在 cache/ 目录下。")


if __name__ == "__main__":
    main()
