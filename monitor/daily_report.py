#!/usr/bin/env python3
"""
daily_report.py
每日强势港美股报告，推送到飞书。
用法：
    python daily_report.py                    # 推送港股+美股
    python daily_report.py --market hk        # 只推送港股
    python daily_report.py --market us        # 只推送美股
    python daily_report.py --dry-run          # 只打印不推送
    python daily_report.py --top-count 15     # 前15只
"""
import sys
import argparse
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv('env')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def build_feishu_card(title: str, sections: list) -> dict:
    """
    \u6784\u5efa\u98de\u4e66\u5361\u7247\u683c\u5f0f\u6d88\u606f\u3002
    sections: list of (subtitle, markdown_table_str)
    """
    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{title}**\n{datetime.now().strftime('%Y-%m-%d %H:%M')}"
            }
        },
        {"tag": "hr"}
    ]
    for subtitle, table in sections:
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{subtitle}**\n{table}"
            }
        })
        elements.append({"tag": "hr"})

    return {
        "msg_type": "interactive",
        "card": {
            "elements": elements,
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title
                },
                "template": "blue"
            }
        }
    }


def get_performance_table(market_type_str: str, top_count: int) -> tuple:
    """
    \u83b7\u53d6\u5f3a\u52bf\u80a1\u6392\u884c\uff0c\u8fd4\u56de (\u6807\u9898, markdown\u8868\u683c\u5b57\u7b26\u4e32)
    """
    from config import Config, MarketType
    from data_loader import DataLoader
    from update_symbol_list import update_all_symbol_lists

    # \u66f4\u65b0 universe
    update_all_symbol_lists()

    config = Config()
    config.top_performers_count = top_count
    loader = DataLoader(config)
    market_type = MarketType(market_type_str)

    symbols, names, performances, volumes = loader.get_performance_symbols_in_detail(market_type)

    if not symbols:
        return None, None

    # \u6784\u5efa Markdown \u8868\u683c
    if market_type == MarketType.HK_STOCK:
        header = "| \u4ee3\u7801 | \u540d\u79f0 | 20\u65e5\u6da8\u5e45 | 5\u65e5\u5747\u91cf |"
        sep    = "|------|------|------:|------:|"
        rows = []
        for sym, name, perf, vol in zip(symbols, names, performances, volumes):
            code = str(sym).replace('.HK', '')
            rows.append(f"| {code} | {name} | {perf:.1f}% | {vol} |")
        market_label = "\U0001f1ed\U0001f1f0 \u6e2f\u80a1"
        bench = "^HSI"
    else:
        header = "| \u4ee3\u7801 | \u540d\u79f0 | 20\u65e5\u6da8\u5e45 | 5\u65e5\u5747\u91cf |"
        sep    = "|------|------|------:|------:|"
        rows = []
        for sym, name, perf, vol in zip(symbols, names, performances, volumes):
            rows.append(f"| {sym} | {name} | {perf:.1f}% | {vol} |")
        market_label = "\U0001f1fa\U0001f1f8 \u7f8e\u80a1"
        bench = "SPY"

    criteria = (
        f"\u8bc4\u9009\u6807\u51c6\uff1a\u7efc\u5408\u52a8\u91cf\u8bc4\u5206\uff08\u76f8\u5bf9\u5f3a\u5ea6\xd740% + \u91cf\u4ef7\u914d\u5408\xd730% + \u8d8b\u52bf\u5e73\u6ed1\xd730%\uff09\n"
        f"- \u76f8\u5bf9\u5f3a\u5ea6\uff1a\u4e2a\u80a1\u6da8\u5e45 - {bench} \u540c\u671f\u6da8\u5e45\uff08\u8d85\u989d\u6536\u76ca\uff09\n"
        f"- \u91cf\u4ef7\u914d\u5408\uff1a\u8fd120\u65e5\u5747\u91cf / \u524d20\u65e5\u5747\u91cf\uff08>1 \u4ee3\u8868\u653e\u91cf\u4e0a\u6da8\uff09\n"
        f"- \u8d8b\u52bf\u5e73\u6ed1\uff1a\u8fd120\u65e5\u4ef7\u683c\u7ebf\u6027\u56de\u5f52 R\u00b2\uff08\u8d8a\u9ad8\u8d8a\u5e73\u7a33\uff09"
    )
    table = "\n".join([criteria, "", header, sep] + rows[:top_count])
    title = f"{market_label} \u5f3a\u52bf\u80a1 Top{min(top_count, len(symbols))}"
    return title, table


def send_to_feishu(payload: dict, webhook_url: str, dry_run: bool = False) -> bool:
    if dry_run:
        import json
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return True
    import requests
    try:
        resp = requests.post(webhook_url, json=payload,
                             headers={'Content-Type': 'application/json'}, timeout=30)
        result = resp.json()
        if result.get('code') == 0:
            logger.info("\u98de\u4e66\u63a8\u9001\u6210\u529f")
            return True
        else:
            logger.error(f"\u98de\u4e66 API \u9519\u8bef: {result}")
            return False
    except Exception as e:
        logger.error(f"\u63a8\u9001\u5931\u8d25: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="\u6bcf\u65e5\u5f3a\u52bf\u6e2f\u7f8e\u80a1\u62a5\u544a")
    parser.add_argument('--market', choices=['hk', 'us', 'all'], default='all')
    parser.add_argument('--top-count', type=int, default=20)
    parser.add_argument('--dry-run', action='store_true', help='\u53ea\u6253\u5370\u4e0d\u63a8\u9001')
    args = parser.parse_args()

    import os
    webhook_url = os.getenv('FEISHU_WEBHOOK_URL', '')
    if not webhook_url and not args.dry_run:
        logger.error("\u672a\u914d\u7f6e FEISHU_WEBHOOK_URL\uff0c\u8bf7\u5728 env \u6587\u4ef6\u4e2d\u8bbe\u7f6e")
        sys.exit(1)

    sections = []
    markets = ['hk_stock', 'us_stock'] if args.market == 'all' else \
              ['hk_stock'] if args.market == 'hk' else ['us_stock']

    for market_str in markets:
        logger.info(f"\u83b7\u53d6 {market_str} \u5f3a\u52bf\u80a1...")
        title, table = get_performance_table(market_str, args.top_count)
        if title and table:
            sections.append((title, table))
        else:
            logger.warning(f"{market_str} \u65e0\u6570\u636e\uff0c\u8df3\u8fc7")

    if not sections:
        logger.error("\u6240\u6709\u5e02\u573a\u5747\u65e0\u6570\u636e")
        sys.exit(1)

    card_title = f"\U0001f4c8 \u6bcf\u65e5\u5f3a\u52bf\u80a1\u62a5\u544a {datetime.now().strftime('%m/%d')}"
    payload = build_feishu_card(card_title, sections)
    send_to_feishu(payload, webhook_url, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
