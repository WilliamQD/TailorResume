"""OpenAI GPT LLM client."""

from __future__ import annotations

import json
import logging
from typing import TypeVar

import openai
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger(__name__)


def _pydantic_to_strict_schema(model: type[BaseModel]) -> dict:
    """Convert a Pydantic model to an OpenAI-compatible strict JSON schema.

    OpenAI's structured outputs require:
    - additionalProperties: false on every object
    - All properties listed in 'required'
    - No default values in schema
    """
    schema = model.model_json_schema()

    def _make_strict(obj: dict) -> dict:
        if obj.get("type") == "object" and "properties" in obj:
            obj["additionalProperties"] = False
            # All properties must be required for strict mode
            obj["required"] = list(obj["properties"].keys())
            for prop in obj["properties"].values():
                _make_strict(prop)
                # Remove defaults — strict mode doesn't allow them
                prop.pop("default", None)
        if "items" in obj:
            _make_strict(obj["items"])
        if "$ref" in obj:
            pass  # refs are resolved at the top level
        if "anyOf" in obj:
            for item in obj["anyOf"]:
                _make_strict(item)
        return obj

    # Process $defs first
    for defn in schema.get("$defs", {}).values():
        _make_strict(defn)
    _make_strict(schema)
    return schema


class OpenAIClient:
    """Wraps the OpenAI SDK for structured + text completions."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    def complete(self, system: str, user: str, response_model: type[T]) -> T:
        """Use structured outputs (response_format) for reliable JSON."""
        schema = _pydantic_to_strict_schema(response_model)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": schema,
                },
            },
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("OpenAI returned empty content")

        raw = json.loads(content)
        log.debug("OpenAI response keys: %s", list(raw.keys()))
        return response_model.model_validate(raw)

    def complete_text(self, system: str, user: str) -> str:
        """Plain text completion."""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""
