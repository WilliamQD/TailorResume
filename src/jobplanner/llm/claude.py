"""Anthropic Claude LLM client."""

from __future__ import annotations

import json
from typing import TypeVar

import anthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ClaudeClient:
    """Wraps the Anthropic SDK for structured + text completions."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, system: str, user: str, response_model: type[T]) -> T:
        """Use tool_use to get structured JSON matching a Pydantic model."""
        schema = response_model.model_json_schema()
        tool = {
            "name": "structured_output",
            "description": "Return the structured result.",
            "input_schema": schema,
        }
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[tool],
            tool_choice={"type": "tool", "name": "structured_output"},
        )
        # Extract tool use block
        for block in response.content:
            if block.type == "tool_use":
                return response_model.model_validate(block.input)

        raise RuntimeError("Claude did not return a tool_use block")

    def complete_text(self, system: str, user: str) -> str:
        """Plain text completion."""
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts: list[str] = []
        for block in response.content:
            if block.type == "text":
                parts.append(block.text)
        return "\n".join(parts)
