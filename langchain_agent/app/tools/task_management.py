"""Tools for managing autonomous analysis tasks (CRUD)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

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
            return pool.submit(asyncio.run, coro).result(timeout=15)
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TaskCreateInput(BaseModel):
    goal: str = Field(description="Natural-language task goal, e.g. '每周跟踪AAPL基本面变化'")
    ticker_scope: list[str] = Field(description="Tickers to track, e.g. ['AAPL', 'MSFT']")
    cadence: str = Field(default="manual", description="Cron expression or 'manual'")
    report_template: str = Field(default="fundamental", description="fundamental|comparison|watchlist_review")


class TaskDeleteInput(BaseModel):
    task_id: str = Field(description="Task ID to delete")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool("create_task", args_schema=TaskCreateInput)
def create_task(
    goal: str,
    ticker_scope: list[str],
    cadence: str = "manual",
    report_template: str = "fundamental",
) -> str:
    """Create a new autonomous analysis task.

    Use this when the user wants to set up recurring or one-off analysis tracking
    for specific stocks. Returns the created task details.
    """
    from app.harness.task_spec import TaskSpecStore

    try:
        uid = current_user_id.get()
        store = _run_async(TaskSpecStore.create())
        spec = _run_async(store.create_task(
            user_id=uid,
            goal=goal,
            ticker_scope=ticker_scope,
            cadence=cadence,
            report_template=report_template,
        ))
        _run_async(store.close())
        return json.dumps({
            "status": "ok",
            "message": f"✅ 任务已创建：{goal}",
            "task_id": spec.task_id,
            "ticker_scope": spec.ticker_scope,
        }, ensure_ascii=False)
    except Exception as exc:
        logger.warning("create_task failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


@tool("list_tasks")
def list_tasks() -> str:
    """List all autonomous tasks for the user.

    Returns task IDs, goals, tickers, status, and cadence.
    """
    from app.harness.task_spec import TaskSpecStore

    try:
        uid = current_user_id.get()
        store = _run_async(TaskSpecStore.create())
        tasks = _run_async(store.list_tasks(uid))
        _run_async(store.close())
        if not tasks:
            return json.dumps({"message": "暂无任务。", "tasks": []}, ensure_ascii=False)
        items = [{
            "task_id": t.task_id,
            "goal": t.goal,
            "ticker_scope": t.ticker_scope,
            "status": t.status,
            "cadence": t.cadence,
        } for t in tasks]
        return json.dumps({"count": len(items), "tasks": items}, ensure_ascii=False)
    except Exception as exc:
        logger.warning("list_tasks failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


@tool("delete_task", args_schema=TaskDeleteInput)
def delete_task(task_id: str) -> str:
    """Delete an autonomous task by its ID.

    Use this when the user wants to remove a task.
    """
    from app.harness.task_spec import TaskSpecStore

    try:
        uid = current_user_id.get()
        store = _run_async(TaskSpecStore.create())
        deleted = _run_async(store.delete_task(uid, task_id))
        _run_async(store.close())
        if deleted:
            return json.dumps({"status": "ok", "message": f"任务 {task_id} 已删除"}, ensure_ascii=False)
        return json.dumps({"status": "ok", "message": f"任务 {task_id} 未找到"}, ensure_ascii=False)
    except Exception as exc:
        logger.warning("delete_task failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})
