"""Evaluation: LLM-as-Judge quality scoring.

Uses the same reflection prompt as ``reflect_node`` to score reports offline.
Can run against saved report snapshots without re-invoking the full pipeline.

Usage::

    pytest eval/test_llm_judge.py -v                # requires LLM API
    pytest eval/test_llm_judge.py -v -k "mock"      # mock-only, no API
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Sample reports for scoring
# ---------------------------------------------------------------------------

_GOOD_REPORT = """\
# AAPL 基本面深度分析

## 盈利能力
- 毛利率: 45.0% (行业领先)
- 营业利润率: 30.2%
- 净利率: 25.3%
- ROE: 150.2% (极高, 因回购导致权益缩小)

## 增长趋势
- 营收同比增长: 8.1%
- 利润同比增长: 12.4%
- 服务业务持续高增长, 硬件稳健

## 估值水平
- P/E: 28.5x (略高于历史均值)
- P/B: 45.0x
- EV/EBITDA: 22.0x

## 财务健康
- 资产负债率: 1.8x (偏高但现金流强劲)
- 流动比率: 1.0x

## 风险因素
1. 中国市场竞争加剧
2. 反垄断监管压力
3. AI 投入产出不确定性

## 投资亮点
- Apple Intelligence 生态布局
- 服务业务毛利率持续提升
- 强劲的资本回报计划
"""

_BAD_REPORT = """\
AAPL is a good stock. You should buy it.
The PE ratio is around 30 which is fine.
Revenue is growing. That's all I know.
"""


# ---------------------------------------------------------------------------
# Helper: invoke the reflect prompt
# ---------------------------------------------------------------------------

async def _run_judge(report_text: str) -> dict[str, Any]:
    """Call the same reflection logic used in reflect_node."""
    from app.agents.nodes import _REFLECT_SYSTEM
    from app.llm.factory import get_tool_calling_llm

    llm = get_tool_calling_llm()
    resp = await llm.ainvoke([
        {"role": "system", "content": _REFLECT_SYSTEM},
        {"role": "user", "content": f"请评估以下分析报告：\n\n{report_text[:3000]}"},
    ])
    raw = resp.content or ""
    import re
    json_match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
    start = raw.find("{")
    if start >= 0:
        return json.loads(raw[start:])
    return {"score": 0, "feedback": "Failed to parse judge response"}


# ---------------------------------------------------------------------------
# Tests with mock LLM (no API required)
# ---------------------------------------------------------------------------

class TestLLMJudgeMock:
    """Test the judge logic with mocked LLM responses."""

    @pytest.mark.asyncio
    async def test_high_score_report(self):
        """Good report should receive score >= 7."""
        mock_response = AsyncMock()
        mock_response.content = json.dumps({
            "score": 8.5,
            "dimensions": {
                "data_completeness": 9,
                "logical_consistency": 8,
                "risk_coverage": 8,
                "actionability": 9,
                "expression_quality": 8,
            },
            "feedback": "报告质量优秀，数据维度覆盖全面。"
        })

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response

        with patch("app.llm.factory.get_tool_calling_llm", return_value=mock_llm):
            result = await _run_judge(_GOOD_REPORT)

        assert result["score"] >= 7.0
        assert "dimensions" in result

    @pytest.mark.asyncio
    async def test_low_score_report(self):
        """Bad report should receive score < 7."""
        mock_response = AsyncMock()
        mock_response.content = json.dumps({
            "score": 3.5,
            "dimensions": {
                "data_completeness": 2,
                "logical_consistency": 4,
                "risk_coverage": 2,
                "actionability": 5,
                "expression_quality": 4,
            },
            "feedback": "报告过于简略，缺乏数据支撑。"
        })

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response

        with patch("app.llm.factory.get_tool_calling_llm", return_value=mock_llm):
            result = await _run_judge(_BAD_REPORT)

        assert result["score"] < 7.0

    @pytest.mark.asyncio
    async def test_reflect_node_integration(self):
        """reflect_node should return score and feedback in state update."""
        from app.agents.nodes import reflect_node

        mock_response = AsyncMock()
        mock_response.content = '```json\n{"score": 8.0, "dimensions": {}, "feedback": "Good"}\n```'

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response

        state: dict[str, Any] = {
            "structured_report": {"profitability": {"gross_margin": 0.45}},
            "analysis_result": {"report": _GOOD_REPORT},
            "revision_count": 0,
        }

        with patch("app.llm.factory.get_tool_calling_llm", return_value=mock_llm):
            result = await reflect_node(state)

        assert result["reflection_score"] == 8.0
        assert result["current_step"] == "reflect_done"

    @pytest.mark.asyncio
    async def test_reflect_node_triggers_revision(self):
        """reflect_node with low score should set revision_count=1."""
        from app.agents.nodes import reflect_node

        mock_response = AsyncMock()
        mock_response.content = '{"score": 4.0, "dimensions": {}, "feedback": "需要补充风险分析"}'

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_response

        state: dict[str, Any] = {
            "structured_report": {"profitability": {}},
            "analysis_result": {"report": _BAD_REPORT},
            "revision_count": 0,
        }

        with patch("app.llm.factory.get_tool_calling_llm", return_value=mock_llm):
            result = await reflect_node(state)

        assert result["reflection_score"] == 4.0
        assert result.get("revision_count") == 1
        assert result.get("reflection_feedback") == "需要补充风险分析"

    @pytest.mark.asyncio
    async def test_reflect_node_skip_when_no_report(self):
        """reflect_node should skip with score=10 when no report exists."""
        from app.agents.nodes import reflect_node

        state: dict[str, Any] = {
            "structured_report": None,
            "analysis_result": {},
        }
        result = await reflect_node(state)
        assert result["reflection_score"] == 10.0
        assert result["current_step"] == "reflect_skipped"


# ---------------------------------------------------------------------------
# Tests with real LLM (requires API key)
# ---------------------------------------------------------------------------

class TestLLMJudgeReal:
    """End-to-end LLM judge scoring. Requires running LLM provider.

    Skip with ``-k 'not real'``.
    """

    @pytest.mark.asyncio
    async def test_good_report_scores_high(self):
        try:
            result = await _run_judge(_GOOD_REPORT)
        except Exception as exc:
            pytest.skip(f"LLM unavailable: {exc}")

        print(f"\nGood report score: {result.get('score')}")
        print(f"Feedback: {result.get('feedback', '')[:100]}")
        assert result.get("score", 0) >= 6.0, f"Expected >= 6, got {result.get('score')}"

    @pytest.mark.asyncio
    async def test_bad_report_scores_low(self):
        try:
            result = await _run_judge(_BAD_REPORT)
        except Exception as exc:
            pytest.skip(f"LLM unavailable: {exc}")

        print(f"\nBad report score: {result.get('score')}")
        print(f"Feedback: {result.get('feedback', '')[:100]}")
        assert result.get("score", 10) <= 7.0, f"Expected <= 7, got {result.get('score')}"

    @pytest.mark.asyncio
    async def test_score_gap_exists(self):
        """Good report must score significantly higher than bad report."""
        try:
            good_result = await _run_judge(_GOOD_REPORT)
            bad_result = await _run_judge(_BAD_REPORT)
        except Exception as exc:
            pytest.skip(f"LLM unavailable: {exc}")

        gap = good_result.get("score", 0) - bad_result.get("score", 0)
        print(f"\nScore gap: {gap:.1f} (good={good_result.get('score')}, bad={bad_result.get('score')})")
        assert gap >= 2.0, f"Expected gap >= 2.0, got {gap:.1f}"
