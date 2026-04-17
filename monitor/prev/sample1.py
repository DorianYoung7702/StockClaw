# requirements:
# pip install pandas yfinance requests beautifulsoup4 lxml tqdm

import pandas as pd
import requests
from bs4 import BeautifulSoup
import yfinance as yf
import time
from tqdm import tqdm
from math import ceil
from urllib.parse import urlparse, unquote, urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from io import StringIO
import re
import json
import os
from pathlib import Path

def _build_retrying_session() -> requests.Session:
    session = requests.Session()
    # Disable reading proxy settings from env to avoid accidental proxychains/env proxies
    session.trust_env = False
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _wikipedia_rest_html_url(page_url: str) -> str | None:
    try:
        parsed = urlparse(page_url)
        if not parsed.path.startswith("/wiki/"):
            return None
        title = parsed.path[len("/wiki/") :]
        # Keep percent-encoding for special chars as REST API expects it
        # but normalize spaces
        title = title.replace(" ", "_")
        return f"{parsed.scheme}://{parsed.netloc}/api/rest_v1/page/html/{title}"
    except Exception:
        return None

def _fetch_html(url: str) -> str:
    session = _build_retrying_session()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/141.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/ *;q=0.8".replace(" ", ""),
        "Accept-Language": "en-US,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }

    # Try normal page first
    resp = session.get(url, headers=headers, timeout=20)
    return resp

def _fetch_wiki_html(url: str) -> str:
    resp = _fetch_html(url)
    if resp.ok and resp.text:
        return resp.text

    # Fallback to REST HTML (usually cleaner for parsing)
    rest_url = _wikipedia_rest_html_url(url)
    if rest_url:
        resp2 = _fetch_html(rest_url)
        if resp2.ok and resp2.text:
            return resp2.text

    # Final fallback: m.wikipedia (sometimes lighter)
    parsed = urlparse(url)
    mobile_host = parsed.netloc.replace("en.wikipedia.org", "en.m.wikipedia.org")
    mobile_url = f"{parsed.scheme}://{mobile_host}{parsed.path}"
    resp3 = _fetch_html(mobile_url)
    resp3.raise_for_status()
    return resp3.text


# ---------------- Cache Utilities ----------------
CACHE_DIR = Path("data_cache")

def _ensure_cache_dir() -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.json"

def load_cached_list(name: str) -> list[str] | None:
    _ensure_cache_dir()
    path = _cache_path(name)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(x) for x in data]
    except Exception:
        return None
    return None

def save_cached_list(name: str, items: list[str]) -> None:
    _ensure_cache_dir()
    path = _cache_path(name)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(list(items), f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ----- 1) 抓取成分列表（示例：S&P500、Nasdaq-100 via Wikipedia） -----
def tickers_from_wikipedia(url, ticker_col_name_candidates=['Symbol','Ticker']):
    html = _fetch_wiki_html(url)
    tables = pd.read_html(StringIO(html))
    # 找到包含 Symbol/Ticker 的表
    for t in tables:
        for cand in ticker_col_name_candidates:
            if cand in t.columns:
                return (
                    t[cand]
                    .astype(str)
                    .str.replace(r"\..*", "", regex=True)
                    .str.strip()
                    .tolist()
                )
    return []

sp500_url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
nasdq100_url = "https://en.wikipedia.org/wiki/Nasdaq-100"

def get_sp500_tickers(force_refresh: bool=False) -> list[str]:
    if not force_refresh:
        cached = load_cached_list("sp500")
        if cached is not None:
            return cached
    tickers = tickers_from_wikipedia(sp500_url)
    save_cached_list("sp500", tickers)
    return tickers

def get_nas100_tickers(force_refresh: bool=False) -> list[str]:
    if not force_refresh:
        cached = load_cached_list("nas100")
        if cached is not None:
            return cached
    tickers = tickers_from_wikipedia(nasdq100_url, ['Ticker','Ticker symbol','Ticker symbol(s)','Symbol'])
    save_cached_list("nas100", tickers)
    return tickers

# ----- 1b) Russell-2000: 推荐做法（示例：使用 iShares IWM 的持仓 CSV 作为代理） -----
# 手动方法：去 https://www.ishares.com/us/products/239710/ishares-russell-2000-etf#Holdings 下载 CSV
# 也可以用 requests/BeautifulSoup 自动抓取 holdings 下载链接（页面有时需要 JS；若遇到困难可手动下载）
# 假设你把 CSV 存为 'IWM_holdings.csv'
def fetch_ishares_r2000_json(save_path: str="rus2k.json") -> None:
    try:
        holdings_page_url = "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf#Holdings"
        resp = _fetch_html(holdings_page_url)
        resp.raise_for_status()
        html_text = resp.text

        match = re.search(r'<div[^>]*id="allHoldingsTab"[^>]*data-ajaxUri="([^"]+)"', html_text, re.IGNORECASE)
        if not match:
            print("Could not locate holdings AJAX URL on iShares page.")
            return

        ajax_path = match.group(1)
        ajax_url = urljoin("https://www.ishares.com", ajax_path)

        session = _build_retrying_session()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/141.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain;q=0.9,*/ *;q=0.8".replace(" ", ""),
            "Accept-Language": "en-US,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

        rj = session.get(ajax_url, headers=headers, timeout=20)
        rj.raise_for_status()

        with open(save_path, "w", encoding="utf-8") as f:
            f.write(rj.text)

        print("Saved iShares holdings JSON to", save_path, "bytes:", len(rj.text))
        print("JSON preview (first 900 chars):")
        print(rj.text[:900])
    except Exception as e:
        print("Error fetching iShares holdings JSON:", e)

def _read_json_text_forgiving(path: str) -> dict | list | None:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except Exception:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start_obj = text.find("{")
    start_arr = text.find("[")
    candidates = [s for s in (start_obj, start_arr) if s != -1]
    if not candidates:
        return None
    start = min(candidates)
    end_obj = text.rfind("}")
    end_arr = text.rfind("]")
    end = max(end_obj, end_arr)
    if end <= start:
        return None
    try:
        return json.loads(text[start:end+1])
    except Exception:
        return None

def _extract_tickers_from_json(data: dict | list) -> list[str]:
    tickers: set[str] = set()

    def add(sym: str) -> None:
        s = sym.strip().upper()
        if 0 < len(s) <= 10 and all(c.isalnum() or c in ".-" for c in s):
            tickers.add(s)

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                kl = str(k).lower()
                if kl in {"ticker", "symbol", "ticker_symbol", "tickersymbol"}:
                    if isinstance(v, str):
                        add(v)
                # Some iShares payloads use "aaData" or similar arrays
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return sorted(tickers)

def get_r2000_tickers_from_ishares_json(path: str = "rus2k.json") -> list[str]:
    data = _read_json_text_forgiving(path)
    if data is None:
        return []
    try:
        return _extract_tickers_from_json(data)
    except Exception:
        return []

def main():
    sp500 = get_sp500_tickers()
    nas100 = get_nas100_tickers()
    print(f"S&P500 tickers: {len(sp500)}; Nasdaq-100 tickers: {len(nas100)}")

    # Fetch iShares JSON (cached on disk by filename); not parsed into tickers here
    fetch_ishares_r2000_json("rus2k.json")

    # Russell-2000 tickers parsed from saved iShares JSON
    r2000_list: list[str] = get_r2000_tickers_from_ishares_json("rus2k.json")

    # ----- 2) 合并所有要查询的标的（去重） -----
    all_tickers = set(sp500 + nas100 + r2000_list)
    all_tickers = sorted([t for t in all_tickers if t and t.upper()!='NAN'])
    print("Total tickers to fetch:", len(all_tickers))

    # ----- 3) 批量用 yfinance 下载历史价量（分块 + 容错） -----
    def fetch_histories(tickers, period_days=10, batch_size=200, sleep_between=2.0):
        """
        返回 dict: ticker -> DataFrame(history)
        我们会请求 period='10d'，取最近 5 个有效交易日
        """
        histories = {}
        n_batches = ceil(len(tickers)/batch_size)
        for i in range(n_batches):
            batch = tickers[i*batch_size:(i+1)*batch_size]
            # yfinance can accept list of tickers
            try:
                data = yf.download(batch, period=f"{period_days}d", threads=True, progress=False)
                # yf.download with multiple tickers returns MultiIndex columns; normalize it
                if isinstance(data.columns, pd.MultiIndex):
                    for sym in batch:
                        try:
                            df = data.xs(sym, axis=1, level=1).dropna(how='all')
                            if not df.empty:
                                histories[sym] = df
                        except Exception:
                            continue
                else:
                    # single ticker in batch
                    if batch:
                        histories[batch[0]] = data
            except Exception as e:
                print("batch fetch error:", e, " — retrying individually")
                # 逐个重试
                for sym in batch:
                    try:
                        df = yf.download(sym, period=f"{period_days}d", threads=False, progress=False)
                        if not df.empty:
                            histories[sym] = df
                    except Exception:
                        continue
            time.sleep(sleep_between)
        return histories

    # 注意：为了示范，先只取前 100 tickers；实际你可以把 all_tickers 全量传入（但耗时较长）
    sample_tickers = list(all_tickers)[:100]
    hist_dict = fetch_histories(sample_tickers, period_days=10, batch_size=50, sleep_between=1.5)
    print("Fetched histories for:", len(hist_dict))

    # ----- 4) 计算每只票过去 5 个交易日的平均成交额（每日 Close*Volume -> 取最后 5 日平均） -----
    import numpy as np

    def avg_dollar_volume(hist_df, lookback_days=5):
        # hist_df 需包含 'Close' 和 'Volume'
        if 'Close' not in hist_df.columns or 'Volume' not in hist_df.columns:
            return np.nan
        df = hist_df[['Close','Volume']].dropna()
        # 取最近 lookback_days 个交易日（如果历史不足则返回 nan）
        if len(df) < lookback_days:
            return np.nan
        last = df.tail(lookback_days)
        daily_dollar = last['Close'] * last['Volume']
        return float(daily_dollar.mean())

    rows = []
    for sym, df in hist_dict.items():
        val = avg_dollar_volume(df, lookback_days=5)
        rows.append({'ticker': sym, 'avg_dollar_volume_5d': val})

    res = pd.DataFrame(rows).dropna().sort_values('avg_dollar_volume_5d', ascending=False).reset_index(drop=True)
    print("Top 10 by 5d avg dollar volume (sample):")
    print(res.head(10))

    # 若要得到前 500，直接对所有标的跑一遍，然后 res.head(500)
    # res.head(500).to_csv('top500_by_5d_dollar_volume.csv', index=False)


if __name__ == "__main__":
    main()
