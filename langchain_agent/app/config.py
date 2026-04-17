"""Centralised configuration loaded from environment variables."""

from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MONITOR_MODULE_ROOT = PROJECT_ROOT.parent / "monitor"


class LLMProvider(str, Enum):
    MINIMAX = "minimax"
    DEEPSEEK = "deepseek"
    ZHIPU = "zhipu"
    OPENAI_COMPATIBLE = "openai_compatible"


def _find_env_file() -> str:
    """Return the first env file that exists: .env, env, or ../monitor/env."""
    for candidate in [
        PROJECT_ROOT / ".env",
        PROJECT_ROOT / "env",
        MONITOR_MODULE_ROOT / "env",
    ]:
        if candidate.exists():
            return str(candidate)
    return str(PROJECT_ROOT / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM ---
    # Default: MiniMax M2.7 — set MINIMAX_API_KEY in .env (no group_id required for current API).
    llm_provider: LLMProvider = LLMProvider.MINIMAX
    minimax_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("MINIMAX_API_KEY", "minimax_api_key"),
    )
    deepseek_api_key: str = ""
    zhipu_api_key: str = ""
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"),
    )
    openai_base_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_BASE_URL", "openai_base_url"),
    )

    # Model selection per role (defaults are DeepSeek-compatible; minimax provider overrides below)
    tool_calling_model: str = "deepseek-chat"
    reasoning_model: str = "deepseek-chat"
    tool_calling_temperature: float = 0.0
    reasoning_temperature: float = 0.3
    max_tokens: int = 4096

    # --- Response policy (integration test / demo) ---
    # auto: follow user language; zh: force Simplified Chinese on all user-visible text.
    atlas_force_response_locale: Literal["auto", "zh"] = Field(
        default="zh",
        validation_alias=AliasChoices("ATLAS_FORCE_RESPONSE_LOCALE", "atlas_force_response_locale"),
    )

    # --- Financial Data Provider ---
    # "eastmoney" (free, best for HK/CN) | "yfinance" (free, US) | "fmp" (paid) | "openbb" | "mock"
    financial_data_provider: str = Field(
        default="eastmoney",
        validation_alias=AliasChoices("FINANCIAL_DATA_PROVIDER", "financial_data_provider"),
    )
    fmp_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("FMP_API_KEY", "fmp_api_key"),
        description="Financial Modeling Prep API key. Get one at https://financialmodelingprep.com/",
    )

    # --- Finnhub (free tier: 60 calls/min, company news with summaries) ---
    finnhub_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("FINNHUB_API_KEY", "finnhub_api_key"),
        description="Finnhub API key. Free at https://finnhub.io/register",
    )

    # --- OpenBB ---
    openbb_token: str = ""

    # --- Notification ---
    feishu_webhook_url: str = ""

    # --- LangSmith ---
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "atlas-fundamental-agent"
    langsmith_endpoint: str = Field(
        default="https://api.smith.langchain.com",
        validation_alias=AliasChoices("LANGSMITH_ENDPOINT", "langsmith_endpoint"),
        description="LangSmith API endpoint. Change for self-hosted LangSmith.",
    )

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    # --- API Auth ---
    api_token: str = Field(
        default="",
        validation_alias=AliasChoices("ATLAS_API_TOKEN", "api_token"),
        description="Bearer token for API authentication. Empty string = auth disabled (dev mode).",
    )
    datasource_encryption_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ATLAS_DATASOURCE_ENCRYPTION_KEY",
            "DATASOURCE_ENCRYPTION_KEY",
            "datasource_encryption_key",
        ),
        description=(
            "Fernet key for encrypting datasource API keys in SQLite. "
            "If empty, a derived key from ATLAS_API_TOKEN is used."
        ),
    )

    # --- Paths ---
    monitor_module_root: Path = MONITOR_MODULE_ROOT
    cache_dir: Path = PROJECT_ROOT / "cache"
    checkpoint_db_path: str = Field(
        default=str(PROJECT_ROOT / "db" / "atlas_sessions.db"),
        validation_alias=AliasChoices("CHECKPOINT_DB_PATH", "checkpoint_db_path"),
        description="SQLite path for LangGraph AsyncSqliteSaver. Set to ':memory:' to disable persistence.",
    )
    chroma_persist_directory: Path = Field(
        default=PROJECT_ROOT / "data" / "chroma",
        validation_alias=AliasChoices("CHROMA_PERSIST_DIR", "chroma_persist_directory"),
    )

    # --- Fundamental RAG (Chroma, session-scoped retrieval) ---
    fundamental_rag_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("RAG_FUNDAMENTAL_ENABLED", "fundamental_rag_enabled"),
    )
    fundamental_rag_top_k: int = Field(
        default=5,
        validation_alias=AliasChoices("RAG_FUNDAMENTAL_TOP_K", "fundamental_rag_top_k"),
    )
    fundamental_rag_max_chunks_per_ingest: int = Field(
        default=32,
        validation_alias=AliasChoices("RAG_FUNDAMENTAL_MAX_CHUNKS", "fundamental_rag_max_chunks_per_ingest"),
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias=AliasChoices("EMBEDDING_MODEL", "embedding_model"),
    )
    embedding_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("EMBEDDING_API_KEY", "OPENAI_API_KEY", "embedding_api_key"),
    )
    embedding_base_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("EMBEDDING_BASE_URL", "OPENAI_BASE_URL", "embedding_base_url"),
    )

    # --- Harness: Context Engineering ---
    harness_model_context_limit: int = Field(
        default=128_000,
        description="Model context window size in tokens (used by TokenBudgetManager).",
    )
    harness_compaction_threshold: float = Field(
        default=0.85,
        description="Fraction of context limit that triggers conversation compaction.",
    )
    resident_default_interval_seconds: int = Field(
        default=300,
        description="Default resident-agent cycle interval in seconds (>=60). "
                    "300s is tuned for a ~2h / 1500 call budget "
                    "(MiniMax M2.7 plan); lower values burn quota faster.",
    )
    harness_compaction_keep_recent: int = Field(
        default=6,
        description="Number of most-recent messages to keep verbatim during compaction.",
    )
    harness_tool_output_max_chars: int = Field(
        default=4_000,
        description="Max characters per tool output before truncation.",
    )

    # --- Harness: Error Recovery ---
    harness_circuit_breaker_threshold: int = Field(
        default=3,
        description="Consecutive failures before circuit breaker trips to OPEN.",
    )
    harness_circuit_breaker_cooldown: int = Field(
        default=60,
        description="Seconds to keep circuit breaker OPEN before allowing a retry.",
    )
    harness_recovery_max_retry: int = Field(
        default=3,
        description="Max retry attempts (Level-1 recovery) per node.",
    )

    # --- Harness: Run Journal ---
    harness_journal_db_path: str = Field(
        default="",
        description="SQLite path for RunJournal. Empty = use checkpoint DB.",
    )

    # --- Harness: Daily Pool Refresh (APScheduler) ---
    pool_refresh_enabled: bool = Field(
        default=True,
        description="Enable APScheduler-driven daily monitor-pool rebuild. "
                    "Replaces monitor/crontab for Docker deployments.",
    )
    pool_refresh_timezone: str = Field(
        default="Asia/Shanghai",
        description="IANA timezone for pool-refresh cron expressions.",
    )
    pool_refresh_us_cron: str = Field(
        default="0 4 * * *",
        description="Cron expression for US-stock pool rebuild (default 04:00 daily).",
    )
    pool_refresh_etf_cron: str = Field(
        default="15 4 * * *",
        description="Cron expression for ETF pool rebuild (default 04:15 daily).",
    )
    pool_refresh_hk_cron: str = Field(
        default="30 17 * * 1-5",
        description="Cron expression for HK-stock pool rebuild (default 17:30 Mon-Fri).",
    )

    # --- Harness: Task Lifecycle ---
    scheduler_enabled: bool = Field(
        default=False,
        description="Enable automatic task scheduling (Phase 2). False = manual trigger only.",
    )
    cycle_timeout_seconds: int = Field(
        default=300,
        description="Max seconds for a single autonomous cycle execution.",
    )
    drift_kpi_miss_streak: int = Field(
        default=3,
        description="Consecutive KPI misses before drift is flagged.",
    )
    drift_quality_decay_threshold: float = Field(
        default=1.5,
        description="Quality score drop threshold for drift detection.",
    )

    @model_validator(mode="after")
    def _normalize_models_and_validate_keys(self) -> "Settings":
        """Align model names with provider (DeepSeek rejects MiniMax-M2.7 with 400 Model Not Exist)."""
        if self.llm_provider == LLMProvider.MINIMAX:
            if self.tool_calling_model in ("deepseek-chat", ""):
                object.__setattr__(self, "tool_calling_model", "MiniMax-M2.7")
            if self.reasoning_model in ("deepseek-chat", ""):
                object.__setattr__(self, "reasoning_model", "MiniMax-M2.7")
        elif self.llm_provider == LLMProvider.DEEPSEEK:
            if "MiniMax" in self.tool_calling_model:
                object.__setattr__(self, "tool_calling_model", "deepseek-chat")
            if "MiniMax" in self.reasoning_model:
                object.__setattr__(self, "reasoning_model", "deepseek-chat")
            if not self.tool_calling_model:
                object.__setattr__(self, "tool_calling_model", "deepseek-chat")
            if not self.reasoning_model:
                object.__setattr__(self, "reasoning_model", "deepseek-chat")
        elif self.llm_provider == LLMProvider.ZHIPU:
            if self.tool_calling_model in ("", "deepseek-chat", "MiniMax-M2.7"):
                object.__setattr__(self, "tool_calling_model", "glm-4-flash")
            if self.reasoning_model in ("", "deepseek-chat", "MiniMax-M2.7"):
                object.__setattr__(self, "reasoning_model", "glm-4-flash")
        elif self.llm_provider == LLMProvider.OPENAI_COMPATIBLE:
            if self.tool_calling_model in ("", "deepseek-chat", "MiniMax-M2.7"):
                object.__setattr__(self, "tool_calling_model", "gpt-4o-mini")
            if self.reasoning_model in ("", "deepseek-chat", "MiniMax-M2.7"):
                object.__setattr__(self, "reasoning_model", "gpt-4o-mini")

        # Auto-promote to FMP when key is present and provider is explicitly set to fmp
        if self.financial_data_provider == "fmp" and not self.fmp_api_key:
            object.__setattr__(self, "financial_data_provider", "eastmoney")

        if self.llm_provider == LLMProvider.MINIMAX and not self.minimax_api_key:
            raise ValueError("MINIMAX_API_KEY is required when LLM_PROVIDER=minimax")
        if self.llm_provider == LLMProvider.DEEPSEEK and not self.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek")
        if self.llm_provider == LLMProvider.ZHIPU and not self.zhipu_api_key:
            raise ValueError("ZHIPU_API_KEY is required when LLM_PROVIDER=zhipu")
        if self.llm_provider == LLMProvider.OPENAI_COMPATIBLE and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai_compatible")
        return self

    def ensure_monitor_importable(self) -> None:
        """Add the monitor/ module to sys.path so we can import it."""
        root = str(self.monitor_module_root)
        if root not in sys.path:
            sys.path.insert(0, root)

    def ensure_cache_dir(self) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir

    def ensure_chroma_persist_dir(self) -> Path:
        """Create Chroma persistence directory (fundamental RAG)."""
        self.chroma_persist_directory.mkdir(parents=True, exist_ok=True)
        return self.chroma_persist_directory


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
