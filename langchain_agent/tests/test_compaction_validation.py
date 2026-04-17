"""Tests for compaction post-validation (_validate_summary).

Verifies:
- Summary that retains all tickers → passes
- Summary that loses >50% tickers → fails
- Summary that loses >70% numbers → fails
- No critical entities in original → always passes
- Edge cases: empty strings, HK tickers, stop-word filtering
"""

from __future__ import annotations

import pytest

from app.harness.compaction import _validate_summary


class TestValidateSummaryTickers:
    def test_all_tickers_retained(self):
        original = "[user] 帮我分析 AAPL 和 NVDA 的基本面"
        summary = "用户请求分析 AAPL 和 NVDA 的基本面数据。"
        assert _validate_summary(original, summary) is True

    def test_half_tickers_retained(self):
        """Exactly 50% retention → should pass (threshold is ≥50%)."""
        original = "[user] 比较 AAPL NVDA MSFT TSLA"
        summary = "用户对比了 AAPL 和 NVDA。"  # 2/4 = 50%
        assert _validate_summary(original, summary) is True

    def test_tickers_lost_below_threshold(self):
        """Only 1/4 retained → 25% < 50% → should fail."""
        original = "[user] 比较 AAPL NVDA MSFT TSLA"
        summary = "用户做了多只股票对比。AAPL 表现最好。"  # 1/4 = 25%
        assert _validate_summary(original, summary) is False

    def test_hk_tickers_retained(self):
        original = "[user] 分析 0700.HK 和 9988.HK"
        summary = "分析了 0700.HK 和 9988.HK 的财务数据。"
        assert _validate_summary(original, summary) is True

    def test_hk_ticker_lost(self):
        original = "[user] 分析 0700.HK 和 9988.HK"
        summary = "对两只港股进行了分析。"  # 0/2
        assert _validate_summary(original, summary) is False

    def test_stop_words_not_counted_as_tickers(self):
        """Common words like 'AI', 'PE', 'ROE' should be filtered out."""
        original = "[user] AAPL 的 PE 和 ROE 怎么样 AI 板块"
        summary = "AAPL 的估值和盈利指标分析。"  # AAPL retained, PE/ROE/AI are stop words
        assert _validate_summary(original, summary) is True


class TestValidateSummaryNumbers:
    def test_numbers_retained(self):
        original = "AAPL 的 PE 是 28.5，毛利率 45.2%，收入 $394B"
        summary = "AAPL PE 为 28.5，毛利率 45.2%，收入 $394B。"
        assert _validate_summary(original, summary) is True

    def test_numbers_lost(self):
        """Lose >70% of significant numbers → should fail."""
        original = "AAPL PE 28.5 毛利 45.2% 收入 $394B 涨幅 12.3% 市值 $3T"
        summary = "AAPL 各项财务指标良好。"  # 0/5 numbers
        assert _validate_summary(original, summary) is False

    def test_few_numbers_not_enforced(self):
        """≤2 numbers in original → number check skipped."""
        original = "AAPL 的趋势评分为 85"
        summary = "AAPL 趋势表现优秀。"  # lost the number but ≤2
        assert _validate_summary(original, summary) is True


class TestValidateSummaryEdgeCases:
    def test_empty_original(self):
        assert _validate_summary("", "anything") is True

    def test_empty_summary(self):
        """If original has tickers but summary is empty → fail."""
        assert _validate_summary("分析 AAPL", "") is False

    def test_no_critical_entities(self):
        """No tickers, no numbers → always pass."""
        original = "你好，今天天气怎么样"
        summary = "用户打了个招呼。"
        assert _validate_summary(original, summary) is True

    def test_mixed_content(self):
        original = "[user] NVDA 毛利率 74.5% 很高 [assistant] 是的，NVDA 盈利能力强劲"
        summary = "NVDA 的毛利率达到 74.5%，盈利能力突出。"
        assert _validate_summary(original, summary) is True
