"""OpenAI Agent node — API key loaded from backend .env only."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

PREVIOUS_DATA_TOKENS = [
    "{{workflow.previous}}",
    "{{workflow.previous()}}",
    "{{dataFlow.previous()}}",
    "{{dataFlow.previous}}",
    "{{previous}}",
]


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
        import re

        message = (user_prompt or "").strip()
        previous_result = context_data.get("previous_result")
        fallback_payload = (
            previous_result
            if previous_result is not None
            else context_data.get("report") or context_data
        )
        previous_str = json.dumps(fallback_payload, indent=2, default=str)

        replaced_any = False

        # 1. Replace {{workflow.previous}} and variations
        for tok in PREVIOUS_DATA_TOKENS:
            if tok in message:
                message = message.replace(tok, previous_str)
                replaced_any = True

        # 2. Replace {{workflow.<node>}} or {{dataFlow.<node>()}}
        node_results = context_data.get("node_results") or {}

        def _resolve_token(match: re.Match) -> str:
            key = match.group(1).lower().strip()
            if key in ("previous", "prev"):
                return previous_str
            if key in node_results:
                return json.dumps(node_results[key], indent=2, default=str)
            if key in context_data:
                return json.dumps(context_data[key], indent=2, default=str)
            return match.group(0)

        new_message = re.sub(
            r"\{\{(?:workflow|dataFlow)\.([a-zA-Z0-9_-]+)(?:\(\))?\}\}",
            _resolve_token,
            message,
        )
        if new_message != message:
            replaced_any = True
            message = new_message

        # 3. Replace direct node tokens like {{report}}, {{tax}}, {{assessor}}, etc.
        for node_name, node_val in node_results.items():
            tok = f"{{{{{node_name}}}}}"
            if tok in message:
                message = message.replace(tok, json.dumps(node_val, indent=2, default=str))
                replaced_any = True

        if "{{report}}" in message:
            rep = context_data.get("report") or node_results.get("report")
            if rep is not None:
                message = message.replace("{{report}}", json.dumps(rep, indent=2, default=str))
                replaced_any = True

        if not message:
            return f"Analyze the following property research data:\n\n{previous_str}"

        # If user wrote a prompt with no variable tokens, append the previous result / context
        if not replaced_any and previous_result is not None:
            prev_label = context_data.get("previous_node") or "Previous Step"
            message = f"{message}\n\n[Data from {prev_label}]:\n{previous_str}"

        return message

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

        # Normalize model aliases
        raw_model = (model or "gpt-4o").strip()
        target_model = raw_model
        lower_model = raw_model.lower()
        if lower_model in ("gpt4.1", "gpt-4-1", "gpt4_1"):
            target_model = "gpt-4.1"
        elif lower_model in ("gpt4.1-mini", "gpt-4-1-mini", "gpt4_1_mini"):
            target_model = "gpt-4.1-mini"
        elif lower_model in ("gpt4.5", "gpt-4-5", "gpt-4.5"):
            target_model = "gpt-4.5-preview"

        logger.info("OpenAI Agent: model=%s (requested=%s) temperature=%s max_tokens=%s", target_model, model, temperature, max_tokens)

        is_reasoning_model = target_model.startswith("o1") or target_model.startswith("o3")
        create_kwargs: dict[str, Any] = {"model": target_model}

        if is_reasoning_model:
            create_kwargs["messages"] = [
                {"role": "developer" if "mini" not in target_model else "user", "content": instructions},
                {"role": "user", "content": user_message},
            ]
            create_kwargs["max_completion_tokens"] = max_tokens
        else:
            create_kwargs["messages"] = [
                {"role": "system", "content": instructions},
                {"role": "user", "content": user_message},
            ]
            create_kwargs["temperature"] = temperature
            create_kwargs["max_tokens"] = max_tokens

        try:
            response = await asyncio.to_thread(client.chat.completions.create, **create_kwargs)
        except Exception as exc:
            err_str = str(exc).lower()
            if "model" in err_str and ("not_found" in err_str or "does not exist" in err_str or "access" in err_str):
                fallback_model = "gpt-4o"
                logger.warning("Model '%s' not accessible (%s). Falling back to '%s'", target_model, exc, fallback_model)
                create_kwargs["model"] = fallback_model
                if is_reasoning_model:
                    create_kwargs.pop("max_completion_tokens", None)
                    create_kwargs["max_tokens"] = max_tokens
                    create_kwargs["temperature"] = temperature
                    create_kwargs["messages"] = [
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": user_message},
                    ]
                response = await asyncio.to_thread(client.chat.completions.create, **create_kwargs)
                target_model = f"{target_model} (fallback: {fallback_model})"
            else:
                raise

        content = response.choices[0].message.content or ""
        usage = response.usage

        return {
            "content": content,
            "model": target_model,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        }
