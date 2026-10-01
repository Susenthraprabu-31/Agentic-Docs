"""OpenAI-first chat completions with Groq fallback on quota/rate-limit errors."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_FALLBACK_MARKERS = (
    "429",
    "rate limit",
    "rate_limit",
    "insufficient_quota",
    "credit_balance_exhausted",
    "you exceeded your current quota",
    "no credits remaining",
    "credits remaining",
    "billing",
    "quota",
)


def should_fallback_to_groq(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _FALLBACK_MARKERS)


def llm_configured() -> bool:
    settings = get_settings()
    return bool(settings.openai_api_key or settings.groq_api_key)


def llm_not_configured_message() -> str:
    return (
        "No LLM API key is set in backend .env. "
        "Add OPENAI_API_KEY and/or GROQ_API_KEY, then restart the server."
    )


def _get_groq_client(api_key: str) -> Any:
    from openai import OpenAI

    return OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")


def _groq_create_kwargs(create_kwargs: dict[str, Any], groq_model: str) -> dict[str, Any]:
    kwargs = dict(create_kwargs)
    kwargs["model"] = groq_model
    if "max_completion_tokens" in kwargs and "max_tokens" not in kwargs:
        kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
    return kwargs


def _create_with_groq_fallback(client: Any, create_kwargs: dict[str, Any]) -> tuple[Any, str]:
    settings = get_settings()
    model_label = str(create_kwargs.get("model", "openai"))
    try:
        response = client.chat.completions.create(**create_kwargs)
        return response, model_label
    except Exception as exc:
        if not settings.groq_api_key or not should_fallback_to_groq(exc):
            raise
        groq_model = settings.groq_model or "llama-3.3-70b-versatile"
        logger.warning(
            "OpenAI chat completion failed (%s). Falling back to Groq model=%s",
            exc,
            groq_model,
        )
        groq_client = _get_groq_client(settings.groq_api_key)
        groq_kwargs = _groq_create_kwargs(create_kwargs, groq_model)
        response = groq_client.chat.completions.create(**groq_kwargs)
        return response, f"groq:{groq_model}"


def chat_completions_create_sync(
    *,
    openai_client: Any,
    create_kwargs: dict[str, Any],
) -> tuple[Any, str]:
    return _create_with_groq_fallback(openai_client, create_kwargs)


async def chat_completions_create(
    *,
    openai_client: Any,
    create_kwargs: dict[str, Any],
) -> tuple[Any, str]:
    return await asyncio.to_thread(_create_with_groq_fallback, openai_client, create_kwargs)
