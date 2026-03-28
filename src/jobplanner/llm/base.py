"""LLMClient protocol — unified interface for all AI providers."""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class LLMClient(Protocol):
    """Minimal interface every LLM provider must implement."""

    def complete(self, system: str, user: str, response_model: type[T]) -> T:
        """Structured output — returns a validated Pydantic model."""
        ...

    def complete_text(self, system: str, user: str) -> str:
        """Plain text completion."""
        ...
