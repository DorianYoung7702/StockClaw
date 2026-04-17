"""Tools for managing user long-term memory (query, delete, clear)."""

from __future__ import annotations

import asyncio
import json
import logging

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.context import current_user_id

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async function from a sync context (LangChain tool)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=10)
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class MemoryQueryInput(BaseModel):
    category: str = Field(default="", description="Optional category filter: preference|analysis_history|learned_pattern. Empty for all.")


class MemoryDeleteInput(BaseModel):
    category: str = Field(description="Memory category, e.g. 'preference'")
    key: str = Field(description="Memory key to delete")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool("list_memories", args_schema=MemoryQueryInput)
def list_memories(category: str = "") -> str:
    """List the user's long-term memories.

    Use this when the user asks to see their saved preferences, analysis history,
    or learned patterns. Can filter by category.
    """
    from app.harness.long_term_memory import LongTermMemory

    try:
        uid = current_user_id.get()
        ltm = _run_async(LongTermMemory.create())
        entries = _run_async(ltm.recall(uid, category=category or None, top_k=50))
        _run_async(ltm.close())

        if not entries:
            return json.dumps({"message": "暂无记忆记录。", "memories": {}}, ensure_ascii=False)

        grouped: dict[str, list[dict]] = {}
        for e in entries:
            grouped.setdefault(e.category, []).append({
                "key": e.key,
                "content": e.content,
            })
        return json.dumps({"total": len(entries), "memories": grouped}, ensure_ascii=False)
    except Exception as exc:
        logger.warning("list_memories failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


@tool("delete_memory", args_schema=MemoryDeleteInput)
def delete_memory(category: str, key: str) -> str:
    """Delete a specific memory entry by category and key.

    Use this when the user asks to forget or remove a specific memory.
    """
    from app.harness.long_term_memory import LongTermMemory

    try:
        uid = current_user_id.get()
        ltm = _run_async(LongTermMemory.create())
        deleted = _run_async(ltm.forget(uid, category, key))
        _run_async(ltm.close())
        if deleted:
            return json.dumps({"status": "ok", "message": f"已删除记忆：{category}/{key}"}, ensure_ascii=False)
        return json.dumps({"status": "ok", "message": f"未找到记忆：{category}/{key}"}, ensure_ascii=False)
    except Exception as exc:
        logger.warning("delete_memory failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


@tool("clear_memories")
def clear_memories() -> str:
    """Clear all long-term memories for the user.

    Use this when the user asks to reset or clear all their saved memories.
    This is destructive — all preferences, history, and patterns will be removed.
    """
    from app.harness.long_term_memory import LongTermMemory

    try:
        uid = current_user_id.get()
        ltm = _run_async(LongTermMemory.create())
        count = _run_async(ltm.forget_old(uid, max_age_days=0))
        _run_async(ltm.close())
        return json.dumps({"status": "ok", "message": f"已清空所有记忆（{count} 条）"}, ensure_ascii=False)
    except Exception as exc:
        logger.warning("clear_memories failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})
