"""Structured Pydantic models for financial data returned by tools."""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Company profile
# ---------------------------------------------------------------------------

class CompanyProfile(BaseModel):
    symbol: str
    name: str
    industry: str = ""
    sector: str = ""
    market_cap: Optional[float] = None
    currency: str = "USD"
    exchange: str = ""
    description: str = ""
    website: str = ""
    employees: Optional[int] = None
    country: str = ""


# ---------------------------------------------------------------------------
# Income statement
# ---------------------------------------------------------------------------

class IncomeStatementRow(BaseModel):
    period: str = Field(description="e.g. '2024-Q4' or '2024'")
    revenue: Optional[float] = None
    cost_of_revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_income: Optional[float] = None
    net_income: Optional[float] = None
    eps: Optional[float] = None
    ebitda: Optional[float] = None


class IncomeStatement(BaseModel):
    symbol: str
    data: list[IncomeStatementRow] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Balance sheet
# ---------------------------------------------------------------------------

class BalanceSheetRow(BaseModel):
    period: str
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    total_equity: Optional[float] = None
    cash_and_equivalents: Optional[float] = None
    total_debt: Optional[float] = None
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None


class BalanceSheet(BaseModel):
    symbol: str
    data: list[BalanceSheetRow] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Cash flow
# ---------------------------------------------------------------------------

class CashFlowRow(BaseModel):
    period: str
    operating_cash_flow: Optional[float] = None
    investing_cash_flow: Optional[float] = None
    financing_cash_flow: Optional[float] = None
    free_cash_flow: Optional[float] = None
    capital_expenditure: Optional[float] = None


class CashFlowStatement(BaseModel):
    symbol: str
    data: list[CashFlowRow] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Key metrics & ratios
# ---------------------------------------------------------------------------

class KeyMetrics(BaseModel):
    symbol: str
    pe_ratio: Optional[float] = Field(None, description="Price / Earnings")
    pb_ratio: Optional[float] = Field(None, description="Price / Book")
    ps_ratio: Optional[float] = Field(None, description="Price / Sales")
    peg_ratio: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    dividend_yield: Optional[float] = None
    roe: Optional[float] = Field(None, description="Return on Equity")
    roa: Optional[float] = Field(None, description="Return on Assets")
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    quick_ratio: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    earnings_growth_yoy: Optional[float] = None
    beta: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None


# ---------------------------------------------------------------------------
# News item
# ---------------------------------------------------------------------------

class NewsItem(BaseModel):
    title: str
    url: str = ""
    published: Optional[date] = None
    source: str = ""
    summary: str = ""
    sentiment: Optional[str] = Field(None, description="positive / neutral / negative")


class CompanyNews(BaseModel):
    symbol: str
    items: list[NewsItem] = Field(default_factory=list)
