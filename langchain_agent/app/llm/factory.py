"""LLM factory — unified creation of chat models for different providers."""

from __future__ import annotations

import hashlib

from langchain_core.language_models.chat_models import BaseChatModel

from app.context import current_user_id
from app.config import LLMProvider
from app.harness.llm_config import ResolvedLLMConfig, get_llm_config_store


def _build_minimax(
    resolved: ResolvedLLMConfig,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    effective_model = model if model is not None else resolved.tool_calling_model
    return ChatOpenAI(
        model=effective_model,
        api_key=resolved.api_key,
        base_url="https://api.minimax.chat/v1",
        temperature=temperature if temperature is not None else resolved.tool_calling_temperature,
        max_tokens=max_tokens or resolved.max_tokens,
    )


def _build_deepseek(
    resolved: ResolvedLLMConfig,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> BaseChatModel:
    # Use ChatOpenAI with DeepSeek's OpenAI-compatible endpoint.
    # ChatDeepSeek triggers Pydantic V1 issues on Python 3.14.
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model or resolved.tool_calling_model,
        api_key=resolved.api_key,
        base_url="https://api.deepseek.com/v1",
        temperature=temperature if temperature is not None else resolved.tool_calling_temperature,
        max_tokens=max_tokens or resolved.max_tokens,
    )


def _build_zhipu(
    resolved: ResolvedLLMConfig,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> BaseChatModel:
    try:
        from langchain_zhipuai import ChatZhipuAI
    except ImportError as exc:
        raise ImportError(
            "langchain-zhipuai is required for Zhipu provider. "
            "Install with: pip install 'atlas-langchain-agent[zhipu]'"
        ) from exc

    return ChatZhipuAI(
        model=model or resolved.tool_calling_model,
        api_key=resolved.api_key,
        temperature=temperature if temperature is not None else resolved.tool_calling_temperature,
        max_tokens=max_tokens or resolved.max_tokens,
    )


def _build_openai_compatible(
    resolved: ResolvedLLMConfig,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model or resolved.tool_calling_model,
        api_key=resolved.api_key,
        base_url=resolved.base_url or "https://api.openai.com/v1",
        temperature=temperature if temperature is not None else resolved.tool_calling_temperature,
        max_tokens=max_tokens or resolved.max_tokens,
    )


_BUILDERS = {
    LLMProvider.MINIMAX: _build_minimax,
    LLMProvider.DEEPSEEK: _build_deepseek,
    LLMProvider.ZHIPU: _build_zhipu,
    LLMProvider.OPENAI_COMPATIBLE: _build_openai_compatible,
}

_MODEL_CACHE: dict[tuple[str, str, str, str, float, int, str], BaseChatModel] = {}


def _resolve_effective_config(user_id: str | None = None) -> ResolvedLLMConfig:
    effective_user_id = user_id or current_user_id.get("default-user")
    return get_llm_config_store().get_effective_config(effective_user_id)


def create_llm_from_config(
    *,
    provider: str,
    api_key: str,
    base_url: str | None = None,
    tool_calling_model: str,
    reasoning_model: str,
    tool_calling_temperature: float = 0.0,
    reasoning_temperature: float = 0.3,
    max_tokens: int = 4096,
    role: str = "tool_calling",
    model: str | None = None,
    temperature: float | None = None,
) -> BaseChatModel:
    resolved = ResolvedLLMConfig(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        tool_calling_model=tool_calling_model,
        reasoning_model=reasoning_model,
        tool_calling_temperature=tool_calling_temperature,
        reasoning_temperature=reasoning_temperature,
        max_tokens=max_tokens,
        enabled=True,
        source="override",
    )
    return _create_from_resolved_config(resolved, role=role, model=model, temperature=temperature, max_tokens=max_tokens)


def _create_from_resolved_config(
    resolved: ResolvedLLMConfig,
    *,
    role: str = "tool_calling",
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    provider: LLMProvider | None = None,
) -> BaseChatModel:
    effective_provider = provider or LLMProvider(resolved.provider)
    builder = _BUILDERS[effective_provider]

    if temperature is None and role == "reasoning":
        temperature = resolved.reasoning_temperature
    elif temperature is None:
        temperature = resolved.tool_calling_temperature
    if model is None and role == "reasoning":
        model = resolved.reasoning_model
    elif model is None:
        model = resolved.tool_calling_model

    key_hash = hashlib.sha256(resolved.api_key.encode("utf-8")).hexdigest()[:12] if resolved.api_key else "nokey"
    cache_key = (
        role,
        effective_provider.value,
        model or "",
        resolved.base_url or "",
        float(temperature if temperature is not None else 0.0),
        int(max_tokens or resolved.max_tokens),
        key_hash,
    )
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    built = builder(resolved, model=model, temperature=temperature, max_tokens=max_tokens)
    _MODEL_CACHE[cache_key] = built
    return built


def create_llm(
    *,
    role: str = "tool_calling",
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    provider: LLMProvider | None = None,
    user_id: str | None = None,
) -> BaseChatModel:
    """Create a chat model instance.

    Args:
        role: ``"tool_calling"`` (default) uses low temperature for deterministic
              tool use; ``"reasoning"`` uses a slightly higher temperature for
              synthesis / narrative generation.
        model: Override the model name from config.
        temperature: Override temperature.
        max_tokens: Override max tokens.
        provider: Override the LLM provider from config.
    """
    resolved = _resolve_effective_config(user_id)
    return _create_from_resolved_config(
        resolved,
        role=role,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        provider=provider,
    )


def get_tool_calling_llm() -> BaseChatModel:
    """Return a cached LLM instance optimised for tool-calling agents."""
    return create_llm(role="tool_calling")


def get_reasoning_llm() -> BaseChatModel:
    """Return a cached LLM instance optimised for reasoning / synthesis."""
    return create_llm(role="reasoning")
