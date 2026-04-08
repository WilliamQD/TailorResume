"""Application configuration and settings."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

log = logging.getLogger(__name__)

# Resolve project root (two levels up from this file when installed editable)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

ModelAlias = Literal[
    "claude-sonnet-4-6", "claude-haiku-4-5", "claude-opus-4-6",
    "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano",
]

# Map friendly names → actual API model IDs
MODEL_MAP: dict[str, str] = {
    "claude-sonnet-4-6": "claude-sonnet-4-6",
    "claude-haiku-4-5": "claude-haiku-4-5-20251001",
    "claude-opus-4-6": "claude-opus-4-6",
    "gpt-5.4": "gpt-5.4",
    "gpt-5.4-mini": "gpt-5.4-mini",
    "gpt-5.4-nano": "gpt-5.4-nano",
}

CLAUDE_MODELS = {"claude-sonnet-4-6", "claude-haiku-4-5", "claude-opus-4-6"}
OPENAI_MODELS = {"gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"}


def _resolve_model(alias: str) -> str:
    """Resolve a model alias to its API model ID."""
    if alias in MODEL_MAP:
        return MODEL_MAP[alias]
    # Allow passing raw model IDs directly
    return alias


def provider_for_model(alias: str) -> Literal["claude", "openai"]:
    """Determine which provider to use for a model alias."""
    if alias in CLAUDE_MODELS or alias.startswith("claude-"):
        return "claude"
    if alias in OPENAI_MODELS or alias.startswith("gpt-"):
        return "openai"
    raise ValueError(f"Unknown model: {alias!r}. Use one of: {list(MODEL_MAP.keys())}")


def _default_data_dir() -> Path:
    """Resolve the personal-data root: JOBPLANNER_DATA_DIR env var, else repo's data/."""
    env = os.environ.get("JOBPLANNER_DATA_DIR", "").strip()
    if env:
        return Path(env)
    return _PROJECT_ROOT / "data"


class Settings(BaseModel):
    """Runtime settings — populated from env vars and CLI flags."""

    model: str = Field(default="gpt-5.4-mini", description="Model alias or raw ID")
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    openai_api_key: str = Field(default="", description="OpenAI API key")

    # Personal-data root: contains experience.yaml and market/skill_tracker.db
    # Defaults to JOBPLANNER_DATA_DIR env var or repo's data/
    data_dir: Path = Field(default_factory=_default_data_dir)
    bank_path: Path | None = None
    tracker_db_path: Path | None = None

    # Template_dir always points at the repo (templates are public assets, not personal data)
    template_dir: Path = Field(default=_PROJECT_ROOT / "data" / "templates")
    output_dir: Path = Field(default=_PROJECT_ROOT / "output")

    max_bullets_per_experience: int = 3
    max_bullets_per_project: int = 2
    max_projects: int = 2
    max_total_bullets: int = 16
    max_retries_for_one_page: int = 8

    latex_compiler: str = "tectonic"

    @model_validator(mode="after")
    def _resolve_data_paths(self) -> "Settings":
        """Fill bank_path and tracker_db_path from data_dir if not explicitly set."""
        if self.bank_path is None:
            self.bank_path = self.data_dir / "experience.yaml"
        if self.tracker_db_path is None:
            self.tracker_db_path = self.data_dir / "market" / "skill_tracker.db"
        return self

    @property
    def resolved_model(self) -> str:
        return _resolve_model(self.model)

    @property
    def provider(self) -> Literal["claude", "openai"]:
        return provider_for_model(self.model)


def _get_secret(name: str) -> str:
    """Retrieve a secret from PowerShell SecretStore. Returns '' on any failure."""
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Get-Secret -Name '{name}' -AsPlainText",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    except Exception:
        log.debug("SecretStore lookup failed for %s", name, exc_info=True)
    return ""


def load_settings(**overrides: object) -> Settings:
    """Create settings from env vars → PowerShell SecretStore fallback, with optional overrides."""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "") or _get_secret("JP-claude-apikey")
    openai_key = os.environ.get("OPENAI_API_KEY", "") or _get_secret("JP-openai-apikey")
    # overrides["model"] takes precedence over JOBPLANNER_MODEL env var
    model = overrides.pop("model", os.environ.get("JOBPLANNER_MODEL", "gpt-5.4-mini"))

    return Settings(
        anthropic_api_key=anthropic_key,
        openai_api_key=openai_key,
        model=model,  # type: ignore[arg-type]
        **overrides,  # type: ignore[arg-type]
    )
