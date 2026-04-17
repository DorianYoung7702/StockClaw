"""Token Budget Manager — manages the LLM's context-window "RAM".

The harness treats the context window as a fixed-size resource and allocates
it across categories with strict priorities so that downstream nodes never
accidentally exceed the model's limit.

Priority order (highest → lowest):
    system_prompt (5%) > long_term_memory (8%) > tool_results (30%)
    > conversation (32%) > rag_context (15%) > completion_buffer (10%)

Usage::

    budget = TokenBudgetManager(model_limit=128_000)
    budget.record("system_prompt", system_text)
    budget.record("tool_results", tool_output)
    if budget.should_compact():
        # trigger compaction before adding more
        ...
    remaining = budget.remaining("conversation")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default allocation ratios (must sum to 1.0)
# ---------------------------------------------------------------------------
DEFAULT_ALLOCATIONS: dict[str, float] = {
    "system_prompt": 0.05,
    "long_term_memory": 0.08,
    "tool_results": 0.30,
    "conversation": 0.32,
    "rag_context": 0.15,
    "completion_buffer": 0.10,
}

# Compaction triggers when total usage exceeds this fraction of model_limit.
# Keep a module-level default, but prefer settings.harness_compaction_threshold at runtime.
COMPACTION_THRESHOLD = 0.85


class RecordResult(NamedTuple):
    """Returned by ``record()`` to signal whether the category is over budget."""
    tokens: int
    over_budget: bool
    used: int
    limit: int

# ---------------------------------------------------------------------------
# Lightweight token estimator (no external dependency required)
# ---------------------------------------------------------------------------

# CJK Unicode ranges — each CJK character ≈ 1-2 tokens
_CJK_RE = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff"
    r"\U00020000-\U0002a6df\U0002a700-\U0002b73f"
    r"\U0002b740-\U0002b81f\U0002b820-\U0002ceaf"
    r"\U0002ceb0-\U0002ebef\U00030000-\U0003134f]"
)


def estimate_tokens(text: str) -> int:
    """Estimate token count without requiring tiktoken.

    Heuristic:
    - CJK characters: ~1.5 tokens each (conservative)
    - ASCII / Latin: ~1 token per 4 characters (GPT-family average)

    This intentionally *over*-estimates to leave headroom.
    """
    if not text:
        return 0
    cjk_chars = len(_CJK_RE.findall(text))
    non_cjk_chars = len(text) - cjk_chars
    return int(cjk_chars * 1.5 + non_cjk_chars / 4)


# ---------------------------------------------------------------------------
# TokenBudgetManager
# ---------------------------------------------------------------------------

@dataclass
class TokenBudgetManager:
    """Tracks per-category token usage against a fixed model context limit.

    This class is stateful — create one per graph invocation (run) and pass
    it through the ``AgentState`` so every node can check / record usage.
    """

    model_limit: int = 128_000
    allocations: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_ALLOCATIONS))
    _usage: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    # -- Recording ----------------------------------------------------------

    def record(self, category: str, text: str) -> RecordResult:
        """Record token usage for *category*.

        Returns a ``RecordResult`` with the token count and whether the
        category has exceeded its allocation.  Callers should check
        ``result.over_budget`` and truncate if needed.
        """
        tokens = estimate_tokens(text)
        self._usage[category] = self._usage.get(category, 0) + tokens
        cat_limit = self.limit_for(category)
        cat_used = self._usage[category]
        over = cat_used > cat_limit > 0
        if over:
            logger.warning(
                "TokenBudget: category '%s' over budget: %d / %d tokens",
                category, cat_used, cat_limit,
            )
        return RecordResult(tokens=tokens, over_budget=over, used=cat_used, limit=cat_limit)

    def set_usage(self, category: str, tokens: int) -> None:
        """Directly set token count (e.g. after compaction replaces content)."""
        self._usage[category] = tokens

    # -- Queries ------------------------------------------------------------

    def used(self, category: str | None = None) -> int:
        """Return tokens used (total or for a specific category)."""
        if category:
            return self._usage.get(category, 0)
        return sum(self._usage.values())

    def limit_for(self, category: str) -> int:
        """Return the absolute token limit for a category."""
        ratio = self.allocations.get(category, 0.0)
        return int(self.model_limit * ratio)

    def remaining(self, category: str) -> int:
        """How many tokens are still available in *category*."""
        return max(0, self.limit_for(category) - self.used(category))

    def usage_ratio(self) -> float:
        """Total usage as a fraction of model_limit (0.0 – 1.0+)."""
        total = self.used()
        return total / self.model_limit if self.model_limit else 0.0

    def should_compact(self) -> bool:
        """Return True when total usage exceeds the compaction threshold.

        Threshold is read from ``Settings.harness_compaction_threshold`` at
        runtime so ops can tune without touching code. Falls back to the
        module-level default if settings are unavailable.
        """
        threshold = COMPACTION_THRESHOLD
        try:
            from app.config import get_settings

            threshold = float(get_settings().harness_compaction_threshold)
        except Exception:
            pass
        return self.usage_ratio() >= threshold

    # -- Enforcement helpers ------------------------------------------------

    def trim_to_budget(self, category: str, text: str) -> str:
        """Truncate *text* so that it fits within *category*'s remaining budget.

        Returns the (possibly shortened) text.  If the text already fits,
        it is returned unchanged.
        """
        avail = self.remaining(category)
        if avail <= 0:
            return ""
        tokens = estimate_tokens(text)
        if tokens <= avail:
            return text
        # Estimate character-to-token ratio from the text itself
        ratio = len(text) / max(tokens, 1)
        target_chars = int(avail * ratio * 0.95)  # 5 % safety margin
        truncated = text[:target_chars]
        logger.info(
            "TokenBudget: trimmed '%s' from %d to ~%d tokens (%d chars)",
            category, tokens, avail, target_chars,
        )
        return truncated

    def rebalance(self) -> None:
        """Redistribute unused budget from idle categories to overflowing ones.

        Call this after the first recording pass so that categories with zero
        usage donate their allocation to those that exceed theirs.
        """
        idle_surplus = 0.0
        overflowing: list[str] = []
        for cat, ratio in self.allocations.items():
            used = self._usage.get(cat, 0)
            limit = int(self.model_limit * ratio)
            if used == 0 and cat != "completion_buffer":
                idle_surplus += ratio
            elif used > limit:
                overflowing.append(cat)

        if not idle_surplus or not overflowing:
            return

        bonus = idle_surplus / len(overflowing)
        new_alloc = dict(self.allocations)
        for cat in list(new_alloc):
            used = self._usage.get(cat, 0)
            limit = int(self.model_limit * new_alloc[cat])
            if used == 0 and cat != "completion_buffer":
                new_alloc[cat] = 0.001  # near-zero, not fully zero
            elif cat in overflowing:
                new_alloc[cat] += bonus
        self.allocations = new_alloc
        logger.info(
            "TokenBudget: rebalanced — freed %.1f%% from idle categories → %s",
            idle_surplus * 100, overflowing,
        )

    # -- Serialisation (for AgentState persistence) -------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_limit": self.model_limit,
            "usage": dict(self._usage),
            "usage_ratio": round(self.usage_ratio(), 3),
            "should_compact": self.should_compact(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TokenBudgetManager":
        mgr = cls(model_limit=data.get("model_limit", 128_000))
        for cat, tokens in data.get("usage", {}).items():
            mgr._usage[cat] = tokens
        return mgr

    # -- Logging helper -----------------------------------------------------

    def log_summary(self) -> None:
        """Emit an INFO-level summary of current budget usage."""
        total = self.used()
        ratio = self.usage_ratio()
        details = ", ".join(f"{k}={v}" for k, v in sorted(self._usage.items()))
        logger.info(
            "TokenBudget: %d / %d (%.1f%%) — %s%s",
            total,
            self.model_limit,
            ratio * 100,
            details,
            " [COMPACT NEEDED]" if self.should_compact() else "",
        )
