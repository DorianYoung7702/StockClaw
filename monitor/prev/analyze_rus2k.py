import json
from pathlib import Path
from typing import Any


def _read_json_text_forgiving(path: Path) -> Any | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    # First, try direct JSON parse
    try:
        return json.loads(text)
    except Exception:
        pass
    # Try to locate the outermost JSON object/array inside any wrapper text
    start_obj = text.find("{")
    start_arr = text.find("[")
    starts = [s for s in [start_obj, start_arr] if s != -1]
    if not starts:
        return None
    start = min(starts)
    # Heuristic: scan from the end to find last closing brace/bracket
    end_obj = text.rfind("}")
    end_arr = text.rfind("]")
    end = max(end_obj, end_arr)
    if end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except Exception:
        return None


def _extract_tickers(value: Any) -> set[str]:
    tickers: set[str] = set()

    def add_if_ticker(s: str) -> None:
        sym = s.strip().upper()
        # Basic sanity: letters, digits, dot/hyphen allowed
        if 0 < len(sym) <= 10 and all(c.isalnum() or c in ".-" for c in sym):
            tickers.add(sym)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                kl = str(k).lower()
                if kl in {"ticker", "symbol", "ticker_symbol", "tickersymbol", "isin_ticker"}:
                    if isinstance(v, str):
                        add_if_ticker(v)
                # Recurse
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        # primitives ignored beyond direct string keys above

    walk(value)
    return tickers


def main() -> None:
    path = Path("rus2k.json")
    if not path.exists():
        print("File not found:", path)
        return

    data = _read_json_text_forgiving(path)
    if data is None:
        print("Could not parse JSON (even with forgiving extraction).")
        return

    # High-level description
    def describe(node: Any, depth: int = 0) -> None:
        prefix = "  " * depth
        if isinstance(node, dict):
            print(prefix + f"dict with {len(node)} keys")
            # show up to first 20 keys
            keys = list(node.keys())[:20]
            print(prefix + "keys:", keys)
        elif isinstance(node, list):
            print(prefix + f"list with {len(node)} items")
            if node:
                print(prefix + "first item type:", type(node[0]).__name__)
        else:
            print(prefix + f"{type(node).__name__}")

    print("Top-level structure:")
    describe(data, 0)

    # Collect likely tickers
    tickers = _extract_tickers(data)
    print(f"\nGuessed tickers found: {len(tickers)}")
    if tickers:
        sample = sorted(tickers)[:25]
        print("Sample:", sample)

    # Try to locate common holdings containers
    def find_paths_to_lists(node: Any, path: str = "$") -> list[str]:
        paths: list[str] = []
        if isinstance(node, list):
            paths.append(path)
        elif isinstance(node, dict):
            for k, v in node.items():
                kl = str(k).lower()
                if kl in {"holdings", "positions", "aadata", "data", "fundholdings"}:
                    if isinstance(v, list):
                        paths.append(f"{path}.{k}")
                paths.extend(find_paths_to_lists(v, f"{path}.{k}"))
        return paths

    list_paths = find_paths_to_lists(data)
    print("\nCandidate list paths (holdings-like):")
    for p in sorted(set(list_paths))[:20]:
        print("  ", p)


if __name__ == "__main__":
    main()


