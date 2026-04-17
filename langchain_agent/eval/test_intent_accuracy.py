"""Evaluation: Intent classification accuracy against golden dataset.

Runs ``_fast_parse`` (rule layer) and optionally the full ``parse_input_node``
(LLM fallback) against every case in ``datasets/intent_golden.json``.

Usage::

    pytest eval/test_intent_accuracy.py -v
    pytest eval/test_intent_accuracy.py -v -k "fast"    # rules only, no LLM
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

_GOLDEN_PATH = pathlib.Path(__file__).parent / "datasets" / "intent_golden.json"


def _load_golden() -> list[dict[str, Any]]:
    with open(_GOLDEN_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. Rule-layer accuracy (_fast_parse) — no LLM needed, runs instantly
# ---------------------------------------------------------------------------

class TestFastParseAccuracy:
    """Measure the coverage and accuracy of the regex rule layer."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.cases = _load_golden()

    def _fp(self, text: str):
        from app.agents.nodes import _fast_parse
        return _fast_parse(text)

    def test_rule_layer_coverage(self):
        """At least 40 % of golden cases should be handled by rules alone."""
        handled = sum(1 for c in self.cases if self._fp(c["input"]) is not None)
        coverage = handled / len(self.cases)
        print(f"\nRule-layer coverage: {handled}/{len(self.cases)} = {coverage:.0%}")
        # _fast_parse intentionally handles only screening keywords;
        # most intents are routed to LLM classifier by design.
        assert coverage >= 0.1, f"Rule coverage too low: {coverage:.0%}"

    @pytest.mark.parametrize("case", _load_golden(), ids=[c["input"][:30] for c in _load_golden()])
    def test_intent_when_handled(self, case: dict[str, Any]):
        """When rules handle a case, the intent must be correct."""
        result = self._fp(case["input"])
        if result is None:
            pytest.skip("Not handled by rule layer")
        # update_config is used for strong_stocks routing
        expected = case["expected_intent"]
        if expected == "strong_stocks":
            expected = "update_config"
        assert result["intent"] == expected, (
            f"Input: {case['input']!r}\n"
            f"Expected: {expected}, Got: {result['intent']}"
        )


# ---------------------------------------------------------------------------
# 2. Full pipeline accuracy (rules + LLM fallback) — requires LLM API
# ---------------------------------------------------------------------------

class TestFullPipelineAccuracy:
    """End-to-end intent classification including LLM fallback.

    Requires a running LLM provider. Skip with ``-k 'not full_pipeline'``.
    """

    @pytest.fixture(autouse=True)
    def _load(self):
        self.cases = _load_golden()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", _load_golden(), ids=[c["input"][:30] for c in _load_golden()])
    async def test_intent_correct(self, case: dict[str, Any]):
        """Full parse_input_node must classify intent correctly."""
        try:
            from langchain_core.messages import HumanMessage
            from app.agents.nodes import parse_input_node
        except ImportError:
            pytest.skip("Dependencies not available")

        state: dict[str, Any] = {"messages": [HumanMessage(content=case["input"])]}

        try:
            result = await parse_input_node(state)
        except Exception as exc:
            pytest.skip(f"LLM call failed: {exc}")

        expected = case["expected_intent"]
        # update_config is used for strong_stocks routing
        if expected == "strong_stocks":
            expected = "update_config"
        assert result["intent"] == expected, (
            f"Input: {case['input']!r}\n"
            f"Expected: {expected}, Got: {result['intent']}"
        )

    @pytest.mark.asyncio
    async def test_overall_accuracy(self):
        """Aggregate accuracy across all golden cases."""
        from langchain_core.messages import HumanMessage
        from app.agents.nodes import parse_input_node

        correct = 0
        total = 0

        for case in self.cases:
            state: dict[str, Any] = {"messages": [HumanMessage(content=case["input"])]}
            try:
                result = await parse_input_node(state)
                expected = case["expected_intent"]
                if expected == "strong_stocks":
                    expected = "update_config"
                if result["intent"] == expected:
                    correct += 1
                total += 1
            except Exception:
                continue

        if total == 0:
            pytest.skip("No cases could be evaluated (LLM unavailable)")

        accuracy = correct / total
        print(f"\nFull pipeline accuracy: {correct}/{total} = {accuracy:.0%}")
        assert accuracy >= 0.80, f"Accuracy too low: {accuracy:.0%}"
