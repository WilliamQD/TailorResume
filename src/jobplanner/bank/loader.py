"""Load and validate the experience bank from YAML."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from jobplanner.bank.schema import ExperienceBank


def load_bank(path: Path) -> ExperienceBank:
    """Load experience.yaml and validate against the Pydantic schema.

    Raises ``ValidationError`` with details if the YAML is malformed or
    missing required fields.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raise ValueError(f"Experience bank is empty: {path}")
    return ExperienceBank.model_validate(raw)


def validate_bank(path: Path) -> list[str]:
    """Return a list of human-readable validation warnings (empty = all good)."""
    warnings: list[str] = []
    try:
        bank = load_bank(path)
    except (ValidationError, ValueError, yaml.YAMLError) as exc:
        return [f"Schema error: {exc}"]

    # Check for duplicate IDs
    exp_ids = [e.id for e in bank.experience]
    proj_ids = [p.id for p in bank.projects]
    for id_ in exp_ids:
        if exp_ids.count(id_) > 1:
            warnings.append(f"Duplicate experience id: {id_!r}")
    for id_ in proj_ids:
        if proj_ids.count(id_) > 1:
            warnings.append(f"Duplicate project id: {id_!r}")

    # Check for empty bullets
    for entry in bank.experience:
        if not entry.bullets:
            warnings.append(f"Experience {entry.id!r} has no bullets")
        for i, b in enumerate(entry.bullets):
            if not b.description.strip():
                warnings.append(f"Experience {entry.id!r} bullet {i} has empty description")
    for entry in bank.projects:
        if not entry.bullets:
            warnings.append(f"Project {entry.id!r} has no bullets")
        for i, b in enumerate(entry.bullets):
            if not b.description.strip():
                warnings.append(f"Project {entry.id!r} bullet {i} has empty description")

    # Check meta
    if not bank.meta.name:
        warnings.append("meta.name is empty")
    if not bank.meta.email:
        warnings.append("meta.email is empty")

    # Check inferred skills
    for inf in bank.inferred_skills:
        if not inf.name.strip():
            warnings.append("Inferred skill has empty name")
        if not inf.basis.strip():
            warnings.append(f"Inferred skill {inf.name!r} has empty basis")

    return warnings
