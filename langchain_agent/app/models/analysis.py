"""Structured models for analysis results produced by agents."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Sub-analyses
# ---------------------------------------------------------------------------

class ProfitabilityAnalysis(BaseModel):
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    summary: str = ""


class GrowthAnalysis(BaseModel):
    revenue_growth_yoy: Optional[float] = None
    earnings_growth_yoy: Optional[float] = None
    revenue_cagr_3y: Optional[float] = None
    summary: str = ""


class ValuationAnalysis(BaseModel):
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    ps_ratio: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    peg_ratio: Optional[float] = None
    summary: str = ""


class FinancialHealthAnalysis(BaseModel):
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    quick_ratio: Optional[float] = None
    free_cash_flow: Optional[float] = None
    summary: str = ""


class SentimentScore(BaseModel):
    overall: str = Field("neutral", description="positive / neutral / negative")
    positive_count: Optional[int] = 0
    negative_count: Optional[int] = 0
    neutral_count: Optional[int] = 0
    key_headlines: list[str] = Field(default_factory=list)
    summary: str = ""

    @field_validator("overall", mode="before")
    @classmethod
    def _coerce_overall(cls, v: Any) -> str:
        return v if isinstance(v, str) and v else "neutral"

    def model_post_init(self, __context: Any) -> None:
        # Coerce None → 0 for count fields (LLMs sometimes emit null)
        if self.positive_count is None:
            object.__setattr__(self, "positive_count", 0)
        if self.negative_count is None:
            object.__setattr__(self, "negative_count", 0)
        if self.neutral_count is None:
            object.__setattr__(self, "neutral_count", 0)


# ---------------------------------------------------------------------------
# Top-level report
# ---------------------------------------------------------------------------

class IntelligenceOverview(BaseModel):
    """Neutral cross-cutting summary of gathered data — not investment advice."""

    summary: str = Field(
        default="",
        description=(
            "2–5 sentences synthesising metrics, sentiment, and context in factual terms only; "
            "must not include buy/sell/hold, price targets, or portfolio guidance unless the user "
            "explicitly asked for such advice."
        ),
    )


class FundamentalReport(BaseModel):
    """Structured intelligence pack for a single ticker (facts and sources, not advice)."""

    ticker: str
    company_name: str = ""
    industry: str = ""
    current_price: Optional[float] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # intelligence_overview: str → {"summary": str}
            io = data.get("intelligence_overview")
            if isinstance(io, str):
                data["intelligence_overview"] = {"summary": io}
        return data

    profitability: ProfitabilityAnalysis = Field(default_factory=ProfitabilityAnalysis)
    growth: GrowthAnalysis = Field(default_factory=GrowthAnalysis)
    valuation: ValuationAnalysis = Field(default_factory=ValuationAnalysis)
    financial_health: FinancialHealthAnalysis = Field(default_factory=FinancialHealthAnalysis)
    news_sentiment: SentimentScore = Field(default_factory=SentimentScore)

    intelligence_overview: IntelligenceOverview = Field(default_factory=IntelligenceOverview)
    risk_factors: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)

    generated_at: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Strong-stock item (mirrors existing monitor/ output)
# ---------------------------------------------------------------------------

class StrongStockItem(BaseModel):
    symbol: str
    name: str = ""
    performance_20d: Optional[float] = None
    performance_60d: Optional[float] = None
    volume_5d_avg: Optional[float] = None
    momentum_score: Optional[float] = None


class StrongStockList(BaseModel):
    market_type: str
    items: list[StrongStockItem] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.now)
