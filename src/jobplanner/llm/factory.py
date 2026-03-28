"""Factory for creating LLM clients based on configuration."""

from __future__ import annotations

from jobplanner.config import Settings, provider_for_model
from jobplanner.llm.base import LLMClient
from jobplanner.llm.claude import ClaudeClient
from jobplanner.llm.openai_client import OpenAIClient


def create_client(settings: Settings) -> LLMClient:
    """Create the appropriate LLM client based on the configured model."""
    provider = settings.provider
    model_id = settings.resolved_model

    if provider == "claude":
        if not settings.anthropic_api_key:
            raise ValueError(
                "Anthropic API key not found. Set ANTHROPIC_API_KEY env var "
                "or store as 'JP-claude-apikey' in PowerShell SecretStore."
            )
        return ClaudeClient(api_key=settings.anthropic_api_key, model=model_id)  # type: ignore[return-value]

    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError(
                "OpenAI API key not found. Set OPENAI_API_KEY env var "
                "or store as 'JP-openai-apikey' in PowerShell SecretStore."
            )
        return OpenAIClient(api_key=settings.openai_api_key, model=model_id)  # type: ignore[return-value]

    raise ValueError(f"Unknown provider: {provider!r}")
