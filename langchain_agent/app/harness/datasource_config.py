"""Data-source configuration store — per-user API keys + category-level priority.

Two-tier config: global defaults (user_id='__global__') + per-user overrides.
Resolution order: user-level > global > .env fallback.

Tables
------
datasource_config
    user_id TEXT, provider_name TEXT, api_key_encrypted TEXT,
    enabled INTEGER DEFAULT 1, priority_overrides TEXT (JSON),
    PRIMARY KEY (user_id, provider_name)
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    from cryptography.fernet import Fernet, InvalidToken

    _HAS_FERNET = True
except Exception:
    Fernet = Any  # type: ignore[assignment]

    class InvalidToken(Exception):
        pass

    _HAS_FERNET = False

logger = logging.getLogger(__name__)

GLOBAL_USER_ID = "__global__"

# ---------------------------------------------------------------------------
# Fernet encryption for API key persistence
# ---------------------------------------------------------------------------


_fernet: Any = None


def _get_encryption_seed() -> str:
    from app.config import get_settings

    settings = get_settings()
    return settings.datasource_encryption_key or settings.api_token or "atlas-default-key"


def _to_fernet_key(raw_key: str) -> bytes:
    """Normalize arbitrary input into a valid Fernet key.

    Accepts either:
    - a proper Fernet key (44-char urlsafe-base64 string), or
    - any raw secret string, which is SHA-256 hashed and base64-url encoded.
    """
    if not _HAS_FERNET:
        raise RuntimeError("cryptography is not installed; Fernet unavailable")
    candidate = raw_key.encode("utf-8")
    try:
        Fernet(candidate)
        return candidate
    except Exception:
        digest = hashlib.sha256(candidate).digest()
        return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Fernet:
    """Build and cache Fernet instance from settings/env."""
    if not _HAS_FERNET:
        raise RuntimeError("cryptography is not installed; Fernet unavailable")

    global _fernet
    if _fernet is None:
        seed = _get_encryption_seed()
        _fernet = Fernet(_to_fernet_key(seed))
    return _fernet


def _fallback_key_bytes() -> bytes:
    """Compatibility fallback key derivation when cryptography is unavailable."""
    return hashlib.sha256(_get_encryption_seed().encode("utf-8")).digest()


def _encrypt(plain: str) -> str:
    """Encrypt plain text (Fernet preferred; compatibility fallback otherwise)."""
    if _HAS_FERNET:
        return _get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")

    key = _fallback_key_bytes()
    encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(plain.encode("utf-8")))
    return base64.b64encode(encrypted).decode("ascii")


def _decrypt(cipher: str) -> str:
    """Decrypt token string (Fernet preferred; compatibility fallback otherwise)."""
    if _HAS_FERNET:
        try:
            return _get_fernet().decrypt(cipher.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Invalid encrypted datasource API key token") from exc

    key = _fallback_key_bytes()
    encrypted = base64.b64decode(cipher)
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(encrypted)).decode("utf-8")


def _mask_key(key: str) -> str:
    """Return masked version for display: first 4 + **** + last 4."""
    if not key or len(key) <= 8:
        return "****" if key else ""
    return key[:4] + "****" + key[-4:]


# ---------------------------------------------------------------------------
# Provider Catalog — metadata for all 17 supported data sources
# ---------------------------------------------------------------------------

@dataclass
class ProviderMeta:
    """Static metadata for a data source."""
    name: str
    display_name: str
    description: str
    categories: list[str]  # fundamental, news, market, macro
    requires_key: bool = True
    key_env_var: str = ""  # .env variable name for fallback
    signup_url: str = ""
    free_tier: str = ""
    implemented: bool = False  # False = skeleton only


PROVIDER_CATALOG: dict[str, ProviderMeta] = {
    # ── Existing (implemented) ──────────────────────────────────────────
    "yfinance": ProviderMeta(
        name="yfinance",
        display_name="Yahoo Finance",
        description="免费美股数据，基本面/行情/新闻",
        categories=["fundamental", "news", "market"],
        requires_key=False,
        implemented=True,
    ),
    "eastmoney": ProviderMeta(
        name="eastmoney",
        display_name="东方财富",
        description="免费港股/A股数据，财务报表覆盖最广",
        categories=["fundamental", "market"],
        requires_key=False,
        implemented=True,
    ),
    "fmp": ProviderMeta(
        name="fmp",
        display_name="Financial Modeling Prep",
        description="付费高质量美股基本面 + 新闻，稳定无限流",
        categories=["fundamental", "news"],
        requires_key=True,
        key_env_var="FMP_API_KEY",
        signup_url="https://financialmodelingprep.com/",
        free_tier="250次/天",
        implemented=True,
    ),
    "finnhub": ProviderMeta(
        name="finnhub",
        display_name="Finnhub",
        description="免费新闻 API，含标题摘要，60次/分",
        categories=["news"],
        requires_key=True,
        key_env_var="FINNHUB_API_KEY",
        signup_url="https://finnhub.io/register",
        free_tier="60次/分",
        implemented=True,
    ),
    "openbb": ProviderMeta(
        name="openbb",
        display_name="OpenBB",
        description="OpenBB 4.5 聚合多源数据，需 PAT Token",
        categories=["fundamental", "news"],
        requires_key=True,
        key_env_var="OPENBB_TOKEN",
        signup_url="https://openbb.co/",
        implemented=True,
    ),
    # ── New (skeleton) ──────────────────────────────────────────────────
    "alpha_vantage": ProviderMeta(
        name="alpha_vantage",
        display_name="Alpha Vantage",
        description="美股全能数据源：基本面/行情/新闻/情绪",
        categories=["fundamental", "news", "market"],
        requires_key=True,
        key_env_var="ALPHA_VANTAGE_API_KEY",
        signup_url="https://www.alphavantage.co/support/#api-key",
        free_tier="25次/天",
        implemented=False,
    ),
    "polygon": ProviderMeta(
        name="polygon",
        display_name="Polygon.io",
        description="实时/历史行情 + 新闻 + 基本面，覆盖美股",
        categories=["fundamental", "news", "market"],
        requires_key=True,
        key_env_var="POLYGON_API_KEY",
        signup_url="https://polygon.io/",
        free_tier="5次/分",
        implemented=False,
    ),
    "twelve_data": ProviderMeta(
        name="twelve_data",
        display_name="Twelve Data",
        description="技术指标内置，基本面 + 行情",
        categories=["fundamental", "market"],
        requires_key=True,
        key_env_var="TWELVE_DATA_API_KEY",
        signup_url="https://twelvedata.com/",
        free_tier="800次/天",
        implemented=False,
    ),
    "tiingo": ProviderMeta(
        name="tiingo",
        display_name="Tiingo",
        description="IEX 实时行情 + 新闻 + 基本面",
        categories=["fundamental", "news", "market"],
        requires_key=True,
        key_env_var="TIINGO_API_KEY",
        signup_url="https://www.tiingo.com/",
        free_tier="免费注册",
        implemented=False,
    ),
    "tushare": ProviderMeta(
        name="tushare",
        display_name="Tushare",
        description="A股/港股最全数据源，需注册获取 Token",
        categories=["fundamental", "market"],
        requires_key=True,
        key_env_var="TUSHARE_TOKEN",
        signup_url="https://tushare.pro/",
        free_tier="免费注册",
        implemented=False,
    ),
    "akshare": ProviderMeta(
        name="akshare",
        display_name="AKShare",
        description="A股免费数据聚合，无需 API Key",
        categories=["fundamental", "market"],
        requires_key=False,
        implemented=False,
    ),
    "newsapi": ProviderMeta(
        name="newsapi",
        display_name="NewsAPI",
        description="全球新闻聚合，100+ 来源",
        categories=["news"],
        requires_key=True,
        key_env_var="NEWSAPI_KEY",
        signup_url="https://newsapi.org/",
        free_tier="100次/天",
        implemented=False,
    ),
    "sec_edgar": ProviderMeta(
        name="sec_edgar",
        display_name="SEC EDGAR",
        description="美国 SEC 财报原文（10-K/10-Q），免费无限",
        categories=["fundamental"],
        requires_key=False,
        signup_url="https://www.sec.gov/edgar/",
        implemented=False,
    ),
    "fred": ProviderMeta(
        name="fred",
        display_name="FRED",
        description="美联储经济数据（GDP/CPI/利率/就业）",
        categories=["macro"],
        requires_key=True,
        key_env_var="FRED_API_KEY",
        signup_url="https://fred.stlouisfed.org/docs/api/api_key.html",
        free_tier="免费",
        implemented=False,
    ),
    "world_bank": ProviderMeta(
        name="world_bank",
        display_name="World Bank",
        description="全球经济指标（200+ 国家），免费无限",
        categories=["macro"],
        requires_key=False,
        signup_url="https://data.worldbank.org/",
        implemented=False,
    ),
    "sina_finance": ProviderMeta(
        name="sina_finance",
        display_name="新浪财经",
        description="A股/港股/美股实时行情，免费无限",
        categories=["market"],
        requires_key=False,
        implemented=False,
    ),
    "xueqiu": ProviderMeta(
        name="xueqiu",
        display_name="雪球",
        description="雪球社区舆情 + 行情数据",
        categories=["news", "market"],
        requires_key=False,
        implemented=False,
    ),
}

# All category names
CATEGORIES = ["fundamental", "news", "market", "macro"]

# Default priority per category (lower number = higher priority)
DEFAULT_PRIORITIES: dict[str, dict[str, int]] = {
    "fundamental": {"fmp": 1, "yfinance": 2, "eastmoney": 3, "openbb": 4, "alpha_vantage": 5, "polygon": 6, "twelve_data": 7, "tiingo": 8, "tushare": 9, "akshare": 10, "sec_edgar": 11},
    "news": {"finnhub": 1, "fmp": 2, "newsapi": 3, "polygon": 4, "alpha_vantage": 5, "tiingo": 6, "openbb": 7, "yfinance": 8, "xueqiu": 9},
    "market": {"yfinance": 1, "eastmoney": 2, "polygon": 3, "alpha_vantage": 4, "twelve_data": 5, "tiingo": 6, "tushare": 7, "akshare": 8, "sina_finance": 9, "xueqiu": 10},
    "macro": {"fred": 1, "world_bank": 2},
}


# ---------------------------------------------------------------------------
# DataSourceConfigStore — SQLite persistence
# ---------------------------------------------------------------------------

class DataSourceConfigStore:
    """Synchronous SQLite store for data-source configuration."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            from app.config import get_settings
            base = Path(get_settings().checkpoint_db_path).parent
            db_path = base / "datasource_config.db"
        self._db_path = str(db_path)
        self._init_db()

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS datasource_config (
                    user_id TEXT NOT NULL,
                    provider_name TEXT NOT NULL,
                    api_key_encrypted TEXT DEFAULT '',
                    enabled INTEGER DEFAULT 1,
                    priority_overrides TEXT DEFAULT '{}',
                    updated_at REAL DEFAULT (julianday('now')),
                    PRIMARY KEY (user_id, provider_name)
                )
            """)
            conn.commit()

    # ── CRUD ────────────────────────────────────────────────────────────

    def get_user_configs(self, user_id: str) -> list[dict[str, Any]]:
        """Return all provider configs for a user."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM datasource_config WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def upsert_config(
        self,
        user_id: str,
        provider_name: str,
        *,
        api_key: str | None = None,
        enabled: bool | None = None,
        priority_overrides: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Create or update a provider config entry."""
        if provider_name not in PROVIDER_CATALOG:
            raise ValueError(f"Unknown provider: {provider_name}")

        existing = self._get_raw(user_id, provider_name)

        enc_key = existing.get("api_key_encrypted", "") if existing else ""
        if api_key is not None:
            enc_key = _encrypt(api_key) if api_key else ""

        is_enabled = enabled if enabled is not None else (existing.get("enabled", 1) if existing else 1)
        prio = json.dumps(priority_overrides) if priority_overrides is not None else (existing.get("priority_overrides", "{}") if existing else "{}")

        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT INTO datasource_config (user_id, provider_name, api_key_encrypted, enabled, priority_overrides, updated_at)
                VALUES (?, ?, ?, ?, ?, julianday('now'))
                ON CONFLICT(user_id, provider_name) DO UPDATE SET
                    api_key_encrypted = excluded.api_key_encrypted,
                    enabled = excluded.enabled,
                    priority_overrides = excluded.priority_overrides,
                    updated_at = excluded.updated_at
            """, (user_id, provider_name, enc_key, int(is_enabled), prio))
            conn.commit()

        return self._get_dict(user_id, provider_name)

    def delete_config(self, user_id: str, provider_name: str) -> bool:
        """Delete a provider config entry. Returns True if deleted."""
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute(
                "DELETE FROM datasource_config WHERE user_id = ? AND provider_name = ?",
                (user_id, provider_name),
            )
            conn.commit()
            return cur.rowcount > 0

    def batch_upsert(self, user_id: str, configs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Batch update multiple provider configs at once."""
        results = []
        for cfg in configs:
            r = self.upsert_config(
                user_id,
                cfg["provider_name"],
                api_key=cfg.get("api_key"),
                enabled=cfg.get("enabled"),
                priority_overrides=cfg.get("priority_overrides"),
            )
            results.append(r)
        return results

    # ── Priority resolution ────────────────────────────────────────────

    def get_effective_config(self, user_id: str) -> dict[str, dict[str, Any]]:
        """Merge: user-level > global > .env fallback.

        Returns {provider_name: {api_key, enabled, priority_overrides}}.
        """
        result: dict[str, dict[str, Any]] = {}

        # Layer 1: .env fallback — read all known env keys
        from app.config import get_settings
        settings = get_settings()
        env_keys = {
            "fmp": settings.fmp_api_key,
            "finnhub": settings.finnhub_api_key,
            "openbb": settings.openbb_token,
        }
        for pname, meta in PROVIDER_CATALOG.items():
            key_from_env = env_keys.get(pname, "")
            if not key_from_env and meta.key_env_var:
                key_from_env = os.environ.get(meta.key_env_var, "")
            result[pname] = {
                "api_key": key_from_env,
                "enabled": True,
                "priority_overrides": {},
                "source": "env" if key_from_env else "default",
            }

        # Layer 2: global defaults
        for cfg in self.get_user_configs(GLOBAL_USER_ID):
            pname = cfg["provider_name"]
            if pname in result:
                if cfg.get("api_key"):
                    result[pname]["api_key"] = cfg["api_key"]
                    result[pname]["source"] = "global"
                result[pname]["enabled"] = cfg["enabled"]
                result[pname]["priority_overrides"] = cfg.get("priority_overrides", {})

        # Layer 3: user-level overrides
        if user_id and user_id != GLOBAL_USER_ID:
            for cfg in self.get_user_configs(user_id):
                pname = cfg["provider_name"]
                if pname in result:
                    if cfg.get("api_key"):
                        result[pname]["api_key"] = cfg["api_key"]
                        result[pname]["source"] = "user"
                    if cfg.get("enabled") is not None:
                        result[pname]["enabled"] = cfg["enabled"]
                    if cfg.get("priority_overrides"):
                        result[pname]["priority_overrides"] = cfg["priority_overrides"]

        return result

    def get_provider_priority(self, user_id: str, category: str) -> list[str]:
        """Return provider names for *category*, sorted by priority (best first).

        Filters out: disabled providers, providers that don't support the category,
        providers requiring a key but having none configured.
        """
        effective = self.get_effective_config(user_id)
        candidates: list[tuple[int, str]] = []

        for pname, meta in PROVIDER_CATALOG.items():
            if category not in meta.categories:
                continue
            eff = effective.get(pname, {})
            if not eff.get("enabled", True):
                continue
            # Skip providers that require a key but don't have one
            if meta.requires_key and not eff.get("api_key"):
                continue
            # Skip unimplemented providers
            if not meta.implemented:
                continue
            # Determine priority number
            user_prio = eff.get("priority_overrides", {})
            prio_num = user_prio.get(category) if isinstance(user_prio, dict) else None
            if prio_num is None:
                prio_num = DEFAULT_PRIORITIES.get(category, {}).get(pname, 99)
            candidates.append((prio_num, pname))

        candidates.sort(key=lambda t: t[0])
        return [name for _, name in candidates]

    def get_api_key(self, user_id: str, provider_name: str) -> str:
        """Resolve the effective API key for a provider."""
        effective = self.get_effective_config(user_id)
        return effective.get(provider_name, {}).get("api_key", "")

    # ── Internal helpers ───────────────────────────────────────────────

    def _get_raw(self, user_id: str, provider_name: str) -> Optional[dict]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM datasource_config WHERE user_id = ? AND provider_name = ?",
                (user_id, provider_name),
            ).fetchone()
        return dict(row) if row else None

    def _get_dict(self, user_id: str, provider_name: str) -> dict[str, Any]:
        raw = self._get_raw(user_id, provider_name)
        if not raw:
            return {}
        return self._row_to_dict(raw)

    @staticmethod
    def _row_to_dict(row: dict | sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        # Decrypt API key for internal use
        enc = d.pop("api_key_encrypted", "")
        try:
            d["api_key"] = _decrypt(enc) if enc else ""
        except Exception:
            d["api_key"] = ""
        # Parse JSON
        prio_raw = d.get("priority_overrides", "{}")
        try:
            d["priority_overrides"] = json.loads(prio_raw) if isinstance(prio_raw, str) else prio_raw
        except (json.JSONDecodeError, TypeError):
            d["priority_overrides"] = {}
        d["enabled"] = bool(d.get("enabled", 1))
        return d


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_store: DataSourceConfigStore | None = None


def get_datasource_config_store() -> DataSourceConfigStore:
    """Return the singleton DataSourceConfigStore."""
    global _store
    if _store is None:
        _store = DataSourceConfigStore()
    return _store


def mask_api_key(key: str) -> str:
    """Public helper — mask an API key for display."""
    return _mask_key(key)
