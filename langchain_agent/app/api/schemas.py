"""Request / response Pydantic schemas for the API layer."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(description="User message / query")
    session_id: Optional[str] = Field(
        default=None,
        description="Session ID for conversation continuity. Omit to start new session.",
    )
    stream: bool = Field(default=False, description="Enable SSE streaming response")


class AnalyzeRequest(BaseModel):
    ticker: str = Field(description="Stock ticker to analyse, e.g. AAPL")
    session_id: Optional[str] = None
    stream: bool = False
    deep_document_text: Optional[str] = Field(
        default=None,
        description="Optional raw text from 10-K / annual report / MD&A to index for this session before analysis",
    )


class FundamentalDocumentIngestRequest(BaseModel):
    """Ingest listing filings or other deep fundamental text for session-scoped RAG."""

    session_id: str = Field(min_length=1, description="Same thread/session as analyze/chat")
    ticker: str
    text: str = Field(description="Plain text from filings, MD&A, risk factors, etc.")
    doc_label: Optional[str] = Field(
        default=None,
        description="e.g. 2024 Form 10-K — stored in chunk metadata only",
    )


class FundamentalDocumentIngestResponse(BaseModel):
    status: str = "ok"
    session_id: str
    ticker: str
    ingested: bool = True


class StrongStocksRequest(BaseModel):
    market_type: Literal["us_stock", "etf", "hk_stock"] = "us_stock"
    top_count: Optional[int] = Field(
        default=None,
        ge=1, le=100,
        description="Number of top stocks to return per momentum period. Default: 10 (monitor config).",
    )
    rsi_threshold: Optional[float] = Field(
        default=None,
        ge=0.0, le=100.0,
        description="RSI strong-trend threshold. Stocks with RSI above this are labelled 'strong'. Default: 48.0.",
    )
    momentum_days: Optional[list[int]] = Field(
        default=None,
        description="Performance look-back windows in days, e.g. [15, 30, 60]. Default: [15, 30, 60, 120].",
    )
    sort_by: Optional[Literal[
        "momentum_score", "performance_20d", "performance_40d",
        "performance_90d", "performance_180d", "rs_20d",
        "vol_score", "trend_r2", "volume_5d_avg"
    ]] = Field(
        default=None,
        description="Sort results by this field (descending). Default: momentum_score.",
    )
    min_volume_turnover: Optional[float] = Field(
        default=None,
        ge=0,
        description="Minimum 5-day average turnover filter. Default varies by market.",
    )
    top_volume_count: Optional[int] = Field(
        default=None,
        ge=50, le=2000,
        description="Pre-filter: keep only top-N symbols by 5-day avg volume before scoring. Default: 500.",
    )


class SingleStrongStockRequest(BaseModel):
    ticker: str = Field(min_length=1, description="Single ticker to load, e.g. AAPL or 0700")
    market_type: Literal["us_stock", "etf", "hk_stock"] = Field(
        default="us_stock",
        description="Market type used to choose benchmark and symbol normalization.",
    )


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class ChatResponse(BaseModel):
    session_id: str
    message: str
    usage: Optional[dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    config_update: Optional[dict[str, Any]] = Field(
        default=None,
        description="Screening config changes to apply in the frontend (update_config intent)",
    )
    watchlist_update: Optional[list[str]] = Field(
        default=None,
        description="Tickers added to watchlist (watchlist_add / analyze_and_watch intents)",
    )


class AnalyzeResponse(BaseModel):
    ticker: str
    session_id: str
    report: str
    structured: Optional[dict[str, Any]] = Field(
        default=None,
        description="FundamentalReport (intelligence JSON, not advice) or null if generation failed",
    )
    errors: list[str] = Field(default_factory=list, description="Data-quality warnings")
    evidence_chain: list[dict[str, Any]] = Field(default_factory=list, description="Structured evidence items retrieved for the analysis")
    retrieval_debug: dict[str, Any] = Field(default_factory=dict, description="Retrieval parameters and hit summaries for debugging / demo")
    usage: Optional[dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class StrongStocksResponse(BaseModel):
    market_type: str
    stocks: list[dict[str, Any]]
    filters_applied: dict[str, Any] = Field(default_factory=dict, description="Active screening parameters (echoed back)")
    timestamp: datetime = Field(default_factory=datetime.now)


class SingleStrongStockResponse(BaseModel):
    market_type: str
    stock: dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.now)


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    llm_provider: str = ""
    checks: dict[str, bool] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

class WatchlistAddRequest(BaseModel):
    user_id: str = Field(min_length=1, description="Persistent user identifier (provided by OpenClaw)")
    ticker: str = Field(min_length=1, description="Stock ticker to add, e.g. AAPL or 0700.HK")
    note: str = Field(default="", description="Optional memo, e.g. '关注财报日'")


class WatchlistRemoveRequest(BaseModel):
    user_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)


class WatchlistUpdateRequest(BaseModel):
    user_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    note: str = Field(description="New note content")


class WatchlistItem(BaseModel):
    ticker: str
    note: str = ""
    added_at: str


class WatchlistResponse(BaseModel):
    user_id: str
    watchlist: list[WatchlistItem]
    count: int


# ---------------------------------------------------------------------------
# Task Lifecycle
# ---------------------------------------------------------------------------

class TaskCreateRequest(BaseModel):
    user_id: str = Field(min_length=1, description="User identifier")
    goal: str = Field(min_length=1, description="Natural-language task goal")
    ticker_scope: list[str] = Field(min_length=1, description="Tickers to track")
    cadence: str = Field(default="manual", description="Cron expression or 'manual'")
    report_template: Literal["fundamental", "comparison", "watchlist_review"] = "fundamental"
    kpi_constraints: Optional[dict[str, Any]] = Field(
        default=None, description="KPI constraints, e.g. {quality_score_min: 7}")
    stop_conditions: Optional[dict[str, Any]] = Field(
        default=None, description="Stop conditions, e.g. {max_cycles: 52}")
    escalation_policy: Literal["email", "webhook", "in_app", "silent"] = "silent"


class TaskUpdateRequest(BaseModel):
    goal: Optional[str] = None
    ticker_scope: Optional[list[str]] = None
    cadence: Optional[str] = None
    report_template: Optional[str] = None
    kpi_constraints: Optional[dict[str, Any]] = None
    stop_conditions: Optional[dict[str, Any]] = None
    escalation_policy: Optional[str] = None
    status: Optional[Literal["active", "paused", "completed"]] = None


class TaskResponse(BaseModel):
    task_id: str
    user_id: str
    goal: str
    ticker_scope: list[str]
    kpi_constraints: dict[str, Any]
    cadence: str
    report_template: str
    stop_conditions: dict[str, Any]
    escalation_policy: str
    status: str
    created_at: float
    updated_at: float


class TaskListResponse(BaseModel):
    user_id: str
    tasks: list[TaskResponse]
    count: int


# ---------------------------------------------------------------------------
# Resident Agent
# ---------------------------------------------------------------------------

class ResidentAgentUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    interval_seconds: Optional[int] = Field(default=None, ge=60, le=86400)
    run_immediately: bool = True


class ResidentAgentCycleSummary(BaseModel):
    cycle_id: str
    task_id: str
    status: str
    quality_score: float = 0.0
    started_at: float
    completed_at: float = 0.0
    report_markdown: str = ""
    errors: list[str] = Field(default_factory=list)
    product_summary: dict[str, Any] = Field(default_factory=dict)


class ResidentAgentStatusResponse(BaseModel):
    user_id: str
    task_id: str = ""
    enabled: bool = False
    interval_seconds: int = 900
    status: str = "stopped"
    running: bool = False
    last_run_at: float = 0.0
    last_error: str = ""
    updated_at: float = 0.0
    watchlist: list[WatchlistItem] = Field(default_factory=list)
    watchlist_count: int = 0
    recent_cycles: list[ResidentAgentCycleSummary] = Field(default_factory=list)
    latest_cycle: Optional[ResidentAgentCycleSummary] = None


# ---------------------------------------------------------------------------
# DataSource Configuration
# ---------------------------------------------------------------------------

class DataSourceProviderInfo(BaseModel):
    """Static metadata for a data source provider."""
    name: str
    display_name: str
    description: str
    categories: list[str]
    requires_key: bool
    signup_url: str = ""
    free_tier: str = ""
    implemented: bool


class DataSourceConfigItem(BaseModel):
    """Per-provider configuration (for create/update)."""
    provider_name: str = Field(min_length=1)
    api_key: Optional[str] = Field(default=None, description="API key (null = keep existing)")
    enabled: Optional[bool] = None
    priority_overrides: Optional[dict[str, int]] = Field(
        default=None,
        description="Per-category priority numbers, e.g. {\"fundamental\": 1, \"news\": 3}",
    )


class DataSourceConfigUpdate(BaseModel):
    """Batch update request."""
    configs: list[DataSourceConfigItem] = Field(min_length=1)


class DataSourceConfigResponse(BaseModel):
    """Single provider config (API key masked)."""
    provider_name: str
    display_name: str
    has_key: bool
    api_key_masked: str = ""
    enabled: bool
    priority_overrides: dict[str, int]
    source: str = ""  # "env" | "global" | "user" | "default"
    implemented: bool


class DataSourceTestRequest(BaseModel):
    api_key: str = Field(default="", description="API key to test (empty for key-free providers)")


class DataSourceTestResponse(BaseModel):
    provider: str
    success: bool
    message: str
    latency_ms: Optional[float] = None


class LLMProviderInfo(BaseModel):
    name: str
    display_name: str
    description: str
    default_tool_model: str
    default_reasoning_model: str
    signup_url: str = ""
    supports_custom_base_url: bool = False


class LLMConfigItem(BaseModel):
    provider: str = Field(min_length=1)
    api_key: Optional[str] = Field(default=None, description="API key (null = keep existing)")
    base_url: Optional[str] = None
    tool_calling_model: Optional[str] = None
    reasoning_model: Optional[str] = None
    tool_calling_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    reasoning_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=128, le=32768)
    enabled: Optional[bool] = None


class LLMConfigResponse(BaseModel):
    provider: str
    display_name: str
    has_key: bool
    api_key_masked: str = ""
    base_url: Optional[str] = None
    tool_calling_model: str
    reasoning_model: str
    tool_calling_temperature: float
    reasoning_temperature: float
    max_tokens: int
    enabled: bool
    source: str = ""
    supports_custom_base_url: bool = False


class LLMTestRequest(BaseModel):
    provider: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    base_url: Optional[str] = None
    tool_calling_model: Optional[str] = None
    reasoning_model: Optional[str] = None
    tool_calling_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    reasoning_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=128, le=32768)


class LLMQuickLoginRequest(LLMTestRequest):
    pass
