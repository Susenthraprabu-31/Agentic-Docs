"""OpenAI Agent node — API key loaded from backend .env only."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

PREVIOUS_DATA_TOKEN = "{{dataFlow.previous()}}"


class OpenAIAgentService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Any = None

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.openai_api_key)

    def _get_client(self) -> Any:
        if not self.settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is not set in backend .env. Add the key and restart the server."
            )
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.settings.openai_api_key)
        return self._client

    def _build_user_message(self, user_prompt: str, context_data: dict[str, Any]) -> str:
        if PREVIOUS_DATA_TOKEN in user_prompt:
            payload = json.dumps(context_data, indent=2, default=str)
            return user_prompt.replace(PREVIOUS_DATA_TOKEN, payload)
        if user_prompt.strip():
            return user_prompt
        return f"Analyze the following property research data:\n\n{json.dumps(context_data, indent=2, default=str)}"

    async def run(
        self,
        *,
        instructions: str = "You are a helpful AI assistant.",
        user_prompt: str = "",
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 1000,
        context_data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        client = self._get_client()
        user_message = self._build_user_message(user_prompt, context_data or {})

        logger.info("OpenAI Agent: model=%s temperature=%s max_tokens=%s", model, temperature, max_tokens)

        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = response.choices[0].message.content or ""
        usage = response.usage

        return {
            "content": content,
            "model": model,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        }
