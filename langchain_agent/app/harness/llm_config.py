from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import LLMProvider, get_settings
from app.harness.datasource_config import GLOBAL_USER_ID, _decrypt, _encrypt, mask_api_key


@dataclass
class LLMProviderMeta:
    name: str
    display_name: str
    description: str
    default_tool_model: str
    default_reasoning_model: str
    signup_url: str = ""
    supports_custom_base_url: bool = False


@dataclass
class ResolvedLLMConfig:
    provider: str
    api_key: str
    base_url: str | None
    tool_calling_model: str
    reasoning_model: str
    tool_calling_temperature: float
    reasoning_temperature: float
    max_tokens: int
    enabled: bool
    source: str


LLM_PROVIDER_CATALOG: dict[str, LLMProviderMeta] = {
    LLMProvider.MINIMAX.value: LLMProviderMeta(
        name=LLMProvider.MINIMAX.value,
        display_name="MiniMax",
        description="使用 Atlas 默认的 MiniMax 直连能力",
        default_tool_model="MiniMax-M2.7",
        default_reasoning_model="MiniMax-M2.7",
        signup_url="https://www.minimaxi.com/",
    ),
    LLMProvider.DEEPSEEK.value: LLMProviderMeta(
        name=LLMProvider.DEEPSEEK.value,
        display_name="DeepSeek",
        description="DeepSeek 官方 OpenAI 兼容接口",
        default_tool_model="deepseek-chat",
        default_reasoning_model="deepseek-chat",
        signup_url="https://platform.deepseek.com/",
    ),
    LLMProvider.ZHIPU.value: LLMProviderMeta(
        name=LLMProvider.ZHIPU.value,
        display_name="智谱 AI",
        description="智谱官方模型接口，适合中文场景",
        default_tool_model="glm-4-flash",
        default_reasoning_model="glm-4-flash",
        signup_url="https://open.bigmodel.cn/",
    ),
    LLMProvider.OPENAI_COMPATIBLE.value: LLMProviderMeta(
        name=LLMProvider.OPENAI_COMPATIBLE.value,
        display_name="OpenAI 兼容",
        description="支持 OpenAI、硅基流动、OpenRouter 等兼容接口",
        default_tool_model="gpt-4o-mini",
        default_reasoning_model="gpt-4o-mini",
        signup_url="https://platform.openai.com/",
        supports_custom_base_url=True,
    ),
}


class LLMConfigStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            base = Path(get_settings().checkpoint_db_path).parent
            db_path = base / "llm_config.db"
        self._db_path = str(db_path)
        self._init_db()

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_config (
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    api_key_encrypted TEXT DEFAULT '',
                    base_url TEXT DEFAULT '',
                    tool_calling_model TEXT DEFAULT '',
                    reasoning_model TEXT DEFAULT '',
                    tool_calling_temperature REAL DEFAULT 0.0,
                    reasoning_temperature REAL DEFAULT 0.3,
                    max_tokens INTEGER DEFAULT 4096,
                    enabled INTEGER DEFAULT 1,
                    updated_at REAL DEFAULT (julianday('now')),
                    PRIMARY KEY (user_id)
                )
                """
            )
            conn.commit()

    def upsert_config(
        self,
        user_id: str,
        *,
        provider: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        tool_calling_model: str | None = None,
        reasoning_model: str | None = None,
        tool_calling_temperature: float | None = None,
        reasoning_temperature: float | None = None,
        max_tokens: int | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        existing = self._get_raw(user_id)
        current = self._row_to_dict(existing) if existing else {}
        effective_provider = provider or current.get("provider") or get_settings().llm_provider.value
        meta = LLM_PROVIDER_CATALOG.get(effective_provider, LLM_PROVIDER_CATALOG[LLMProvider.MINIMAX.value])

        enc_key = existing.get("api_key_encrypted", "") if existing else ""
        if api_key is not None:
            enc_key = _encrypt(api_key) if api_key else ""

        next_base_url = (base_url if base_url is not None else current.get("base_url")) or ""
        next_tool_model = (tool_calling_model if tool_calling_model is not None else current.get("tool_calling_model")) or meta.default_tool_model
        next_reasoning_model = (reasoning_model if reasoning_model is not None else current.get("reasoning_model")) or meta.default_reasoning_model
        next_tool_temp = float(tool_calling_temperature if tool_calling_temperature is not None else current.get("tool_calling_temperature", 0.0))
        next_reasoning_temp = float(reasoning_temperature if reasoning_temperature is not None else current.get("reasoning_temperature", 0.3))
        next_max_tokens = int(max_tokens if max_tokens is not None else current.get("max_tokens", 4096))
        next_enabled = int(enabled if enabled is not None else current.get("enabled", True))

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO llm_config (
                    user_id, provider, api_key_encrypted, base_url,
                    tool_calling_model, reasoning_model,
                    tool_calling_temperature, reasoning_temperature,
                    max_tokens, enabled, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, julianday('now'))
                ON CONFLICT(user_id) DO UPDATE SET
                    provider = excluded.provider,
                    api_key_encrypted = excluded.api_key_encrypted,
                    base_url = excluded.base_url,
                    tool_calling_model = excluded.tool_calling_model,
                    reasoning_model = excluded.reasoning_model,
                    tool_calling_temperature = excluded.tool_calling_temperature,
                    reasoning_temperature = excluded.reasoning_temperature,
                    max_tokens = excluded.max_tokens,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    effective_provider,
                    enc_key,
                    next_base_url,
                    next_tool_model,
                    next_reasoning_model,
                    next_tool_temp,
                    next_reasoning_temp,
                    next_max_tokens,
                    next_enabled,
                ),
            )
            conn.commit()
        return self.get_user_config(user_id)

    def delete_config(self, user_id: str) -> bool:
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute("DELETE FROM llm_config WHERE user_id = ?", (user_id,))
            conn.commit()
            return cur.rowcount > 0

    def get_user_config(self, user_id: str) -> dict[str, Any]:
        raw = self._get_raw(user_id)
        return self._row_to_dict(raw) if raw else {}

    def get_effective_config(self, user_id: str) -> ResolvedLLMConfig:
        settings = get_settings()
        env_provider = settings.llm_provider.value
        env_api_key = ""
        env_base_url = None
        if env_provider == LLMProvider.MINIMAX.value:
            env_api_key = settings.minimax_api_key
        elif env_provider == LLMProvider.DEEPSEEK.value:
            env_api_key = settings.deepseek_api_key
        elif env_provider == LLMProvider.ZHIPU.value:
            env_api_key = settings.zhipu_api_key
        elif env_provider == LLMProvider.OPENAI_COMPATIBLE.value:
            env_api_key = settings.openai_api_key
            env_base_url = settings.openai_base_url

        result: dict[str, Any] = {
            "provider": env_provider,
            "api_key": env_api_key,
            "base_url": env_base_url,
            "tool_calling_model": settings.tool_calling_model,
            "reasoning_model": settings.reasoning_model,
            "tool_calling_temperature": settings.tool_calling_temperature,
            "reasoning_temperature": settings.reasoning_temperature,
            "max_tokens": settings.max_tokens,
            "enabled": True,
            "source": "env" if env_api_key else "default",
        }

        global_cfg = self.get_user_config(GLOBAL_USER_ID)
        if global_cfg:
            result.update({k: v for k, v in global_cfg.items() if v not in (None, "") or k in {"enabled", "base_url"}})
            result["source"] = "global"

        if user_id and user_id != GLOBAL_USER_ID:
            user_cfg = self.get_user_config(user_id)
            if user_cfg:
                result.update({k: v for k, v in user_cfg.items() if v not in (None, "") or k in {"enabled", "base_url"}})
                result["source"] = "user"

        meta = LLM_PROVIDER_CATALOG.get(result["provider"], LLM_PROVIDER_CATALOG[LLMProvider.MINIMAX.value])
        tool_model = result.get("tool_calling_model") or meta.default_tool_model
        reasoning_model = result.get("reasoning_model") or meta.default_reasoning_model

        return ResolvedLLMConfig(
            provider=str(result.get("provider") or env_provider),
            api_key=str(result.get("api_key") or ""),
            base_url=result.get("base_url") or None,
            tool_calling_model=str(tool_model),
            reasoning_model=str(reasoning_model),
            tool_calling_temperature=float(result.get("tool_calling_temperature", settings.tool_calling_temperature)),
            reasoning_temperature=float(result.get("reasoning_temperature", settings.reasoning_temperature)),
            max_tokens=int(result.get("max_tokens", settings.max_tokens)),
            enabled=bool(result.get("enabled", True)),
            source=str(result.get("source", "default")),
        )

    def _get_raw(self, user_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM llm_config WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _row_to_dict(row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        data = dict(row)
        enc = data.pop("api_key_encrypted", "")
        try:
            data["api_key"] = _decrypt(enc) if enc else ""
        except Exception:
            data["api_key"] = ""
        data["enabled"] = bool(data.get("enabled", 1))
        data["tool_calling_temperature"] = float(data.get("tool_calling_temperature", 0.0))
        data["reasoning_temperature"] = float(data.get("reasoning_temperature", 0.3))
        data["max_tokens"] = int(data.get("max_tokens", 4096))
        return data


_store: LLMConfigStore | None = None


def get_llm_config_store() -> LLMConfigStore:
    global _store
    if _store is None:
        _store = LLMConfigStore()
    return _store


def serialize_llm_config(user_id: str) -> dict[str, Any]:
    cfg = get_llm_config_store().get_effective_config(user_id)
    meta = LLM_PROVIDER_CATALOG.get(cfg.provider, LLM_PROVIDER_CATALOG[LLMProvider.MINIMAX.value])
    return {
        "provider": cfg.provider,
        "display_name": meta.display_name,
        "has_key": bool(cfg.api_key),
        "api_key_masked": mask_api_key(cfg.api_key),
        "base_url": cfg.base_url,
        "tool_calling_model": cfg.tool_calling_model,
        "reasoning_model": cfg.reasoning_model,
        "tool_calling_temperature": cfg.tool_calling_temperature,
        "reasoning_temperature": cfg.reasoning_temperature,
        "max_tokens": cfg.max_tokens,
        "enabled": cfg.enabled,
        "source": cfg.source,
        "supports_custom_base_url": meta.supports_custom_base_url,
    }


def list_llm_providers() -> list[dict[str, Any]]:
    return [
        {
            "name": meta.name,
            "display_name": meta.display_name,
            "description": meta.description,
            "default_tool_model": meta.default_tool_model,
            "default_reasoning_model": meta.default_reasoning_model,
            "signup_url": meta.signup_url,
            "supports_custom_base_url": meta.supports_custom_base_url,
        }
        for meta in LLM_PROVIDER_CATALOG.values()
    ]
