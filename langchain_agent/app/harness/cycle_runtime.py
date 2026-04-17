"""Cycle Runtime — execute one autonomous analysis cycle for a TaskSpec.

This is the core of the autonomous refactor: it wraps the existing LangGraph
agent graph as a repeatable, unattended execution unit.  The existing graph
topology and nodes are reused verbatim; only the initial ``AgentState`` is
constructed differently (with task context injected).

Usage::

    runtime = CycleRuntime()
    result = await runtime.run_cycle(spec)
    # result is a CycleResult persisted to TaskMemory
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage

from app.harness.resident_product import (
    build_symbol_context,
    build_symbol_snapshot,
    build_watchlist_summary,
    dedupe_texts,
    derive_confidence,
    normalize_user_error,
)
from app.harness.task_spec import TaskSpec
from app.harness.task_memory import CycleResult, TaskMemory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Intent inference from TaskSpec
# ---------------------------------------------------------------------------

_TEMPLATE_INTENT_MAP: dict[str, str] = {
    "fundamental": "single_stock",
    "comparison": "compare",
    "watchlist_review": "single_stock",
}


def _infer_intent(spec: TaskSpec) -> str:
    """Map a report_template to the graph intent used in parse_input routing."""
    return _TEMPLATE_INTENT_MAP.get(spec.report_template, "single_stock")


def _build_goal_message(spec: TaskSpec) -> str:
    """Build a natural-language prompt from the task spec that the agent graph
    can parse as if it came from a user."""
    tickers = ", ".join(spec.ticker_scope)
    if spec.report_template == "comparison":
        return f"请对以下标的进行对比分析：{tickers}。{spec.goal}"
    if spec.report_template == "watchlist_review":
        return f"请对我的观察列表进行回顾分析：{tickers}。{spec.goal}"
    # Default: fundamental single/multi
    if len(spec.ticker_scope) == 1:
        return f"请对 {tickers} 进行全面基本面分析。{spec.goal}"
    return f"请依次对以下标的进行基本面分析：{tickers}。{spec.goal}"


# ---------------------------------------------------------------------------
# KPI validation
# ---------------------------------------------------------------------------

def _check_kpi(spec: TaskSpec, result: CycleResult) -> dict[str, Any]:
    """Validate cycle output against the spec's KPI constraints.

    Returns a dict of ``{metric: {"target": …, "actual": …, "pass": bool}}``.
    """
    checks: dict[str, Any] = {}
    constraints = spec.kpi_constraints or {}

    if "quality_score_min" in constraints:
        target = constraints["quality_score_min"]
        checks["quality_score"] = {
            "target": target,
            "actual": result.quality_score,
            "pass": result.quality_score >= target,
        }

    if "max_errors" in constraints:
        target = constraints["max_errors"]
        checks["error_count"] = {
            "target": target,
            "actual": len(result.errors),
            "pass": len(result.errors) <= target,
        }

    return checks


def _is_fatal_symbol_error(error_text: str) -> bool:
    lowered = str(error_text or "").lower()
    non_fatal_markers = (
        "degraded: all data sources failed",
        "could not be verified",
        "所有指标均为空",
        "部分指标缺失",
        "维度数据完全缺失",
        "529",
        "overloaded",
        "负载较高",
    )
    return not any(marker in lowered for marker in non_fatal_markers)


def _summarize_symbol_errors(ticker: str, errors: list[str]) -> list[str]:
    normalized = dedupe_texts([normalize_user_error(err) for err in errors])
    return [f"[{ticker}] {text}" for text in normalized]


# ---------------------------------------------------------------------------
# CycleRuntime
# ---------------------------------------------------------------------------

class CycleRuntime:
    """Execute one autonomous analysis cycle for a TaskSpec.

    Reuses the existing compiled LangGraph agent graph — no topology changes.
    """

    def __init__(self, timeout_seconds: int = 300) -> None:
        self._timeout = timeout_seconds

    async def run_cycle(
        self,
        spec: TaskSpec,
        *,
        prev_summary: Optional[str] = None,
        previous_cycle: Optional[CycleResult] = None,
        recent_drifts: list[dict[str, Any]] | None = None,
    ) -> CycleResult:
        """Run a single cycle and persist the result.

        Parameters
        ----------
        spec : TaskSpec
            The task contract to execute.
        prev_summary : str, optional
            Previous cycle's report summary for continuity injection.

        Returns
        -------
        CycleResult
            The structured outcome of this cycle.
        """
        import asyncio
        from app.dependencies import get_compiled_graph, get_fresh_callbacks
        from app.memory.store import make_thread_config

        cycle_id = CycleResult.new_id()
        started_at = time.time()
        logger.info("Cycle %s starting for task %s (%s)",
                     cycle_id, spec.task_id, spec.goal[:60])

        graph = get_compiled_graph()
        config = make_thread_config()  # fresh session per cycle
        session_id = config["configurable"]["thread_id"]
        callbacks, tracker, journal = get_fresh_callbacks(
            session_id=session_id, user_id=spec.user_id,
        )
        run_config = {**config, "callbacks": callbacks}

        if spec.report_template == "watchlist_review":
            try:
                cycle = await self._run_watchlist_cycle(
                    spec,
                    cycle_id=cycle_id,
                    started_at=started_at,
                    prev_summary=prev_summary,
                    previous_cycle=previous_cycle,
                    recent_drifts=recent_drifts or [],
                )
                try:
                    await journal.flush()
                except Exception:
                    logger.warning("Journal flush failed for cycle %s", cycle_id)
                return cycle
            except Exception as exc:
                logger.error("Watchlist cycle %s failed: %s", cycle_id, exc, exc_info=True)
                return await self._finish_cycle(
                    spec, cycle_id, started_at,
                    status="failed",
                    errors=[f"{type(exc).__name__}: {exc}"],
                )

        # Build initial AgentState
        initial_state = self._build_initial_state(spec, session_id, prev_summary)

        # Execute graph with timeout
        try:
            result_state = await asyncio.wait_for(
                graph.ainvoke(initial_state, config=run_config),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            logger.error("Cycle %s timed out after %ds", cycle_id, self._timeout)
            return await self._finish_cycle(
                spec, cycle_id, started_at,
                status="failed",
                errors=[f"Cycle timed out after {self._timeout}s"],
            )
        except Exception as exc:
            logger.error("Cycle %s failed: %s", cycle_id, exc, exc_info=True)
            return await self._finish_cycle(
                spec, cycle_id, started_at,
                status="failed",
                errors=[f"{type(exc).__name__}: {exc}"],
            )

        # Flush journal
        try:
            await journal.flush()
        except Exception:
            logger.warning("Journal flush failed for cycle %s", cycle_id)

        # Extract results from graph state
        return await self._process_result(
            spec,
            cycle_id,
            started_at,
            result_state,
            recent_drifts=recent_drifts or [],
        )

    # -- Internal helpers ------------------------------------------------------

    def _build_initial_state(
        self,
        spec: TaskSpec,
        session_id: str,
        prev_summary: Optional[str],
    ) -> dict[str, Any]:
        """Construct the AgentState dict that the graph expects."""
        message = _build_goal_message(spec)
        state: dict[str, Any] = {
            "messages": [HumanMessage(content=message)],
            "session_id": session_id,
            "user_id": spec.user_id,
            "task_id": spec.task_id,
        }
        # Inject previous cycle context so synthesis can compare
        if prev_summary:
            state["cycle_context"] = prev_summary
        return state

    async def _run_watchlist_cycle(
        self,
        spec: TaskSpec,
        *,
        cycle_id: str,
        started_at: float,
        prev_summary: Optional[str],
        previous_cycle: Optional[CycleResult],
        recent_drifts: list[dict[str, Any]],
    ) -> CycleResult:
        import asyncio
        from app.dependencies import get_compiled_graph, get_fresh_callbacks
        from app.memory.store import make_thread_config

        graph = get_compiled_graph()
        previous_symbols = self._previous_symbol_map(previous_cycle)
        symbol_summaries: list[dict[str, Any]] = []
        structured_by_symbol: dict[str, Any] = {}
        all_errors: list[str] = []
        fatal_failures = 0
        quality_scores: list[float] = []
        run_ids: list[str] = []

        for ticker in spec.ticker_scope:
            session_config = make_thread_config()
            session_id = session_config["configurable"]["thread_id"]
            callbacks, _, journal = get_fresh_callbacks(
                session_id=session_id,
                user_id=spec.user_id,
                run_metadata={"resident_ticker": ticker, "task_id": spec.task_id},
            )
            run_config = {**session_config, "callbacks": callbacks}
            symbol_context = build_symbol_context(previous_symbols.get(ticker), recent_drifts)
            goal_message = self._build_symbol_goal_message(spec, ticker, symbol_context)
            initial_state: dict[str, Any] = {
                "messages": [HumanMessage(content=goal_message)],
                "session_id": session_id,
                "user_id": spec.user_id,
                "task_id": spec.task_id,
            }
            if prev_summary:
                initial_state["cycle_context"] = prev_summary

            try:
                result_state = await asyncio.wait_for(
                    graph.ainvoke(initial_state, config=run_config),
                    timeout=self._timeout,
                )
                try:
                    await journal.flush()
                except Exception:
                    logger.warning("Journal flush failed for %s/%s", spec.task_id, ticker)

                structured = result_state.get("structured_report") or {}
                symbol_errors = [str(e) for e in (result_state.get("errors") or [])]
                normalized_symbol_errors = dedupe_texts([normalize_user_error(err) for err in symbol_errors])
                quality_score = float(result_state.get("reflection_score", 0.0) or 0.0)
                run_id = str(result_state.get("run_id", "") or "")
                if any(_is_fatal_symbol_error(err) for err in symbol_errors):
                    fatal_failures += 1

                structured_by_symbol[ticker] = structured
                quality_scores.append(quality_score)
                if run_id:
                    run_ids.append(run_id)
                all_errors.extend(_summarize_symbol_errors(ticker, symbol_errors))
                symbol_summaries.append(
                    build_symbol_snapshot(
                        ticker,
                        structured,
                        quality_score=quality_score,
                        errors=normalized_symbol_errors,
                        previous_snapshot=previous_symbols.get(ticker),
                        drift_signals=recent_drifts,
                    )
                )
            except Exception as exc:
                logger.warning("Watchlist symbol analysis failed for %s/%s: %s", spec.task_id, ticker, exc)
                fatal_failures += 1
                snapshot = self._build_failed_symbol_snapshot(
                    ticker,
                    str(exc),
                    previous_symbols.get(ticker),
                    recent_drifts,
                )
                symbol_summaries.append(snapshot)
                all_errors.extend(_summarize_symbol_errors(ticker, [str(exc)]))

        watchlist_summary = build_watchlist_summary(symbol_summaries, drift_signals=recent_drifts)
        overall_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
        status = "success"
        all_errors = dedupe_texts(all_errors)
        if fatal_failures >= max(len(symbol_summaries), 1):
            status = "failed"
        elif all_errors:
            status = "partial"

        cycle = CycleResult(
            cycle_id=cycle_id,
            task_id=spec.task_id,
            started_at=started_at,
            completed_at=time.time(),
            status=status,
            report_markdown=watchlist_summary.get("markdown", ""),
            structured_report={
                "watchlist_summary": watchlist_summary,
                "symbols": structured_by_symbol,
            },
            kpi_check={},
            quality_score=overall_quality,
            errors=all_errors,
            run_id=",".join(run_ids[:5]),
            product_summary={
                "mode": "watchlist_review",
                "watchlist": watchlist_summary,
                "symbols": symbol_summaries,
            },
        )
        cycle.kpi_check = _check_kpi(spec, cycle)
        await self._persist(cycle)
        logger.info(
            "Watchlist cycle %s completed for task %s: status=%s symbols=%d quality=%.1f errors=%d",
            cycle_id, spec.task_id, status, len(symbol_summaries), overall_quality, len(all_errors),
        )
        return cycle

    def _build_symbol_goal_message(self, spec: TaskSpec, ticker: str, symbol_context: str) -> str:
        base = f"请对 {ticker} 进行全面基本面分析，并给出本轮相对上轮的变化结论。{spec.goal}"
        if not symbol_context:
            return base
        return f"{base}\n\n{symbol_context}"

    def _previous_symbol_map(self, previous_cycle: Optional[CycleResult]) -> dict[str, dict[str, Any]]:
        if previous_cycle is None:
            return {}
        summary = previous_cycle.product_summary or {}
        symbols = summary.get("symbols") if isinstance(summary, dict) else []
        if not isinstance(symbols, list):
            return {}
        return {
            str(item.get("ticker", "")): item
            for item in symbols
            if isinstance(item, dict) and item.get("ticker")
        }

    def _build_failed_symbol_snapshot(
        self,
        ticker: str,
        error_text: str,
        previous_snapshot: dict[str, Any] | None,
        recent_drifts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        user_error = normalize_user_error(error_text)
        score, label, reasons = derive_confidence(0.0, errors=[user_error], drift_signals=recent_drifts)
        changes = ["本轮未能完成有效分析，已保留上轮结论作为参考"]
        if previous_snapshot and previous_snapshot.get("stance"):
            changes.append(f"暂时沿用上轮立场：{previous_snapshot.get('stance')}")
        return {
            "ticker": ticker,
            "stance": "warning",
            "change_severity": "major",
            "update_mode": "full_refresh",
            "conclusion": {
                "title": f"{ticker} — warning",
                "summary": "本轮分析未完整完成，已按降级模式保留观察结论。",
                "why": user_error,
                "changes": changes,
                "top_risk": user_error,
                "top_catalyst": "待下轮恢复后重新评估",
                "confidence": label,
                "confidence_score": round(score, 2),
                "confidence_reasons": reasons,
            },
            "metrics": {
                "quality_score": 0.0,
                "sentiment_overall": "unknown",
                "risk_count": 1,
            },
            "highlights": [],
            "risk_factors": [user_error],
            "errors": [user_error],
        }

    async def _process_result(
        self,
        spec: TaskSpec,
        cycle_id: str,
        started_at: float,
        result_state: dict[str, Any],
        *,
        recent_drifts: list[dict[str, Any]] | None = None,
    ) -> CycleResult:
        """Extract meaningful data from the graph result and build CycleResult."""
        # Extract final AI message as report
        markdown = ""
        for m in reversed(result_state.get("messages", [])):
            if isinstance(m, AIMessage) and m.content:
                markdown = m.content
                break

        structured = result_state.get("structured_report") or {}
        quality = result_state.get("reflection_score", 0.0) or 0.0
        errors = result_state.get("errors", [])
        run_id = result_state.get("run_id", "")
        product_summary: dict[str, Any] = {}

        if structured and spec.report_template == "fundamental":
            ticker = str(structured.get("ticker") or result_state.get("resolved_symbol") or "")
            if ticker:
                symbol_summary = build_symbol_snapshot(
                    ticker,
                    structured,
                    quality_score=float(quality or 0.0),
                    errors=[str(e) for e in errors],
                    previous_snapshot=None,
                    drift_signals=recent_drifts or [],
                )
                product_summary = {
                    "mode": "single_stock",
                    "symbols": [symbol_summary],
                    "watchlist": build_watchlist_summary([symbol_summary], drift_signals=recent_drifts or []),
                }

        status = "success"
        if errors:
            status = "partial"

        cycle = CycleResult(
            cycle_id=cycle_id,
            task_id=spec.task_id,
            started_at=started_at,
            completed_at=time.time(),
            status=status,
            report_markdown=markdown,
            structured_report=structured,
            kpi_check={},
            quality_score=quality,
            errors=errors,
            run_id=run_id,
            product_summary=product_summary,
        )

        # KPI validation
        cycle.kpi_check = _check_kpi(spec, cycle)

        # Persist to TaskMemory
        await self._persist(cycle)

        logger.info(
            "Cycle %s completed for task %s: status=%s quality=%.1f errors=%d",
            cycle_id, spec.task_id, cycle.status, cycle.quality_score, len(errors),
        )
        return cycle

    async def _finish_cycle(
        self,
        spec: TaskSpec,
        cycle_id: str,
        started_at: float,
        status: str = "failed",
        errors: list[str] | None = None,
    ) -> CycleResult:
        """Create and persist a failed/partial cycle result."""
        cycle = CycleResult(
            cycle_id=cycle_id,
            task_id=spec.task_id,
            started_at=started_at,
            completed_at=time.time(),
            status=status,
            errors=errors or [],
        )
        await self._persist(cycle)
        return cycle

    async def _persist(self, cycle: CycleResult) -> None:
        """Write cycle result to TaskMemory."""
        try:
            mem = await TaskMemory.create()
            await mem.save_cycle(cycle)
            await mem.close()
        except Exception as exc:
            logger.error("Failed to persist cycle %s: %s", cycle.cycle_id, exc)
