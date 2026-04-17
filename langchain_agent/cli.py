#!/usr/bin/env python3
"""Local CLI for testing fundamental analysis without FastAPI or OpenClaw.

Usage:
    python cli.py analyze AAPL                   # 默认在终端打印工具/节点进度
    python cli.py analyze --quiet AAPL           # 关闭进度，仅输出最终结果
    python cli.py analyze --zh AAPL
    python cli.py chat "分析一下苹果公司的基本面"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

from dotenv import load_dotenv


def _setup() -> None:
    """Load env and configure logging before any app imports."""
    from pathlib import Path

    for candidate in [Path(".env"), Path("env"), Path("../monitor/env")]:
        if candidate.exists():
            load_dotenv(candidate, override=True)
            break


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("yfinance").setLevel(logging.WARNING)


# LangGraph 顶层节点名（用于过滤 astream_events 噪声）
_GRAPH_NODE_NAMES = frozenset({
    "parse_input",
    "resolve_symbol",
    "gather_data",
    "strong_stocks",
    "sentiment",
    "synthesis",
    "validate_result",
    "render_output",
    "chat",
})


async def _run_graph_cli(graph, input_state: dict, config: dict, *, stream: bool) -> dict:
    """Run the LangGraph once. If stream=True, print tool/node progress (astream_events v2)."""
    if not stream:
        return await graph.ainvoke(input_state, config=config)

    print("Progress:", flush=True)
    last_node: str | None = None
    async for event in graph.astream_events(input_state, config=config, version="v2"):
        kind = event.get("event", "")
        name = event.get("name") or ""
        if kind == "on_tool_start" and name:
            print(f"  [tool] {name}", flush=True)
        elif kind == "on_chain_start" and name in _GRAPH_NODE_NAMES:
            if name != last_node:
                print(f"  [node] {name}", flush=True)
                last_node = name

    snap = await graph.aget_state(config)
    if snap is None or snap.values is None:
        return {}
    return dict(snap.values)


async def run_analyze(ticker: str, *, force_zh: bool, stream: bool) -> None:
    """Run the full analysis graph for a single ticker."""
    from langchain_core.messages import AIMessage, HumanMessage

    from app.dependencies import get_compiled_graph
    from app.memory.store import make_thread_config

    graph = get_compiled_graph()
    config = make_thread_config()
    session_id = config["configurable"]["thread_id"]

    if force_zh:
        query = (
            f"请对 {ticker} 做全面的基本面情报汇总：仅整理可核验的数据与公开信息，"
            "用常识性表述说明各维度含义，不要针对任何假设中的个人投资情景做解读或操作建议。"
        )
    else:
        query = f"Please provide a comprehensive fundamental analysis for {ticker}"

    input_state = {
        "messages": [HumanMessage(content=query)],
        "session_id": session_id,
    }

    print(f"\n{'='*60}")
    print(f"  Analyzing: {ticker}" + ("  [zh 测试模式]" if force_zh else ""))
    if stream:
        print("  [进度：工具与节点将逐行显示]")
    print(f"{'='*60}\n")

    result = await _run_graph_cli(graph, input_state, config, stream=stream)

    structured = result.get("structured_report")
    markdown = result.get("markdown_report", "")
    errors = result.get("errors", [])

    if markdown:
        print(markdown)
    else:
        for m in reversed(result.get("messages", [])):
            if isinstance(m, AIMessage) and m.content:
                print(m.content)
                break

    if structured:
        print(f"\n{'='*60}")
        print("  Structured JSON Output")
        print(f"{'='*60}\n")
        print(json.dumps(structured, indent=2, ensure_ascii=False, default=str))

    if errors:
        print(f"\n{'='*60}")
        print("  Warnings / Data Limitations")
        print(f"{'='*60}")
        for e in errors:
            print(f"  - {e}")

    print()


async def run_chat(message: str, *, force_zh: bool, stream: bool) -> None:
    """Run the graph in free-form chat mode."""
    from langchain_core.messages import AIMessage, HumanMessage

    from app.dependencies import get_compiled_graph
    from app.memory.store import make_thread_config

    graph = get_compiled_graph()
    config = make_thread_config()
    session_id = config["configurable"]["thread_id"]

    input_state = {
        "messages": [HumanMessage(content=message)],
        "session_id": session_id,
    }

    if force_zh:
        print("\n[zh 测试模式：ATLAS_FORCE_RESPONSE_LOCALE=zh]\n")
    if stream:
        print("[进度：工具与节点将逐行显示]\n")

    result = await _run_graph_cli(graph, input_state, config, stream=stream)

    markdown = result.get("markdown_report", "")
    if markdown:
        print(f"\n{markdown}\n")
    else:
        for m in reversed(result.get("messages", [])):
            if isinstance(m, AIMessage) and m.content:
                print(f"\n{m.content}\n")
                break

    structured = result.get("structured_report")
    if structured:
        print(json.dumps(structured, indent=2, ensure_ascii=False, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas LangChain local CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("analyze", help="Single-ticker fundamental intelligence run")
    pa.add_argument(
        "--zh",
        action="store_true",
        help="测试：设置 ATLAS_FORCE_RESPONSE_LOCALE=zh，强制简体中文并启用常识性、非情景化回答口径",
    )
    pa.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="不显示执行进度（默认会显示工具与 LangGraph 节点）",
    )
    pa.add_argument(
        "--stream",
        "-s",
        action="store_true",
        help="保留兼容：与默认行为相同（已默认开启进度）",
    )
    pa.add_argument("ticker", help="Ticker or company name")

    pc = sub.add_parser("chat", help="Free-form message through the agent graph")
    pc.add_argument(
        "--zh",
        action="store_true",
        help="同上：强制简体中文（测试 / 演示）",
    )
    pc.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="不显示执行进度",
    )
    pc.add_argument(
        "--stream",
        "-s",
        action="store_true",
        help="保留兼容：与默认行为相同",
    )
    pc.add_argument("message", nargs=argparse.REMAINDER, help="User message (quote if needed)")

    args = parser.parse_args()
    if args.cmd == "chat" and not args.message:
        parser.error("chat requires a non-empty message")

    _setup()
    if args.zh:
        os.environ["ATLAS_FORCE_RESPONSE_LOCALE"] = "zh"

    _setup_logging()

    # 默认显示进度；--quiet 关闭（--stream 仅作旧命令兼容，与默认相同）
    show_progress = not args.quiet

    if args.cmd == "analyze":
        asyncio.run(
            run_analyze(args.ticker.strip(), force_zh=args.zh, stream=show_progress)
        )
    else:
        msg = " ".join(args.message).strip()
        asyncio.run(run_chat(msg, force_zh=args.zh, stream=show_progress))


if __name__ == "__main__":
    main()
