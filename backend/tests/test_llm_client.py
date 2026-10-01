from unittest.mock import MagicMock, patch

import pytest

from app.agents.llm_client import (
    chat_completions_create_sync,
    llm_configured,
    should_fallback_to_groq,
)


@pytest.mark.parametrize(
    "message",
    [
        "Error code: 429 - insufficient_quota",
        "You have no credits remaining",
        "rate limit exceeded",
        "credit_balance_exhausted",
    ],
)
def test_should_fallback_to_groq(message: str):
    assert should_fallback_to_groq(RuntimeError(message)) is True


def test_should_not_fallback_to_groq_for_unrelated_error():
    assert should_fallback_to_groq(RuntimeError("model not found")) is False


def test_llm_configured_accepts_openai_or_groq():
    settings = MagicMock(openai_api_key="", groq_api_key="gsk-test")
    with patch("app.agents.llm_client.get_settings", return_value=settings):
        assert llm_configured() is True

    settings = MagicMock(openai_api_key="sk-test", groq_api_key="")
    with patch("app.agents.llm_client.get_settings", return_value=settings):
        assert llm_configured() is True

    settings = MagicMock(openai_api_key="", groq_api_key="")
    with patch("app.agents.llm_client.get_settings", return_value=settings):
        assert llm_configured() is False


def test_chat_completions_create_sync_uses_groq_on_openai_quota_error():
    openai_client = MagicMock()
    groq_client = MagicMock()
    openai_response = MagicMock()
    groq_response = MagicMock()
    openai_client.chat.completions.create.side_effect = RuntimeError(
        "Error code: 429 - {'error': {'code': 'insufficient_quota'}}"
    )
    groq_client.chat.completions.create.return_value = groq_response

    settings = MagicMock(
        groq_api_key="gsk-test",
        groq_model="llama-3.3-70b-versatile",
    )
    create_kwargs = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "hello"}],
    }

    with patch("app.agents.llm_client.get_settings", return_value=settings), patch(
        "app.agents.llm_client._get_groq_client",
        return_value=groq_client,
    ):
        response, provider = chat_completions_create_sync(
            openai_client=openai_client,
            create_kwargs=create_kwargs,
        )

    assert response is groq_response
    assert provider == "groq:llama-3.3-70b-versatile"
    groq_client.chat.completions.create.assert_called_once()
    groq_kwargs = groq_client.chat.completions.create.call_args.kwargs
    assert groq_kwargs["model"] == "llama-3.3-70b-versatile"
    assert groq_kwargs["messages"] == create_kwargs["messages"]
