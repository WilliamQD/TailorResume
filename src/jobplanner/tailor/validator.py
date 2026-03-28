"""Post-AI hallucination validator for tailored resumes (synthesis mode)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jobplanner.bank.schema import ExperienceBank, TailoredResume


@dataclass
class ValidationWarning:
    severity: str  # "error" | "warning"
    source_id: str
    bullet_index: int
    message: str


@dataclass
class ValidationResult:
    passed: bool
    warnings: list[ValidationWarning] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationWarning]:
        return [w for w in self.warnings if w.severity == "error"]


def _extract_numbers(text: str) -> set[str]:
    """Extract all number-like tokens (integers, decimals, percentages)."""
    return set(re.findall(r"\d+(?:\.\d+)?%?", text))


def validate_tailored_resume(
    tailored: TailoredResume,
    bank: ExperienceBank,
) -> ValidationResult:
    """Validate that the tailored resume doesn't hallucinate.

    Synthesis-mode checks:
    1. Source existence -- every source_id exists in the bank
    2. Bullet index validity -- every index in source_bullet_indices is in range
    3. Metric preservation -- numbers from source bullets appear in output
    4. Skill whitelist -- skills in output text should come from the bank
    """
    warnings: list[ValidationWarning] = []
    all_skills = bank.all_skill_names()

    # Check experiences
    for sel in tailored.selected_experiences:
        entry = bank.get_experience(sel.source_id)
        if entry is None:
            warnings.append(ValidationWarning(
                severity="error",
                source_id=sel.source_id,
                bullet_index=-1,
                message=f"Experience source_id {sel.source_id!r} not found in bank",
            ))
            continue

        for i, tb in enumerate(sel.bullets):
            _check_synthesized_bullet(
                tb.text, tb.source_bullet_indices, entry.bullets,
                sel.source_id, i, all_skills, warnings,
            )

    # Check projects
    for sel in tailored.selected_projects:
        entry = bank.get_project(sel.source_id)
        if entry is None:
            warnings.append(ValidationWarning(
                severity="error",
                source_id=sel.source_id,
                bullet_index=-1,
                message=f"Project source_id {sel.source_id!r} not found in bank",
            ))
            continue

        for i, tb in enumerate(sel.bullets):
            _check_synthesized_bullet(
                tb.text, tb.source_bullet_indices, entry.bullets,
                sel.source_id, i, all_skills, warnings,
            )

    has_errors = any(w.severity == "error" for w in warnings)
    return ValidationResult(passed=not has_errors, warnings=warnings)


def _check_synthesized_bullet(
    output_text: str,
    source_indices: list[int],
    source_bullets: list,
    source_id: str,
    output_index: int,
    all_skills: set[str],
    warnings: list[ValidationWarning],
) -> None:
    """Run checks on a synthesized output bullet vs its source bullets."""
    # Validate indices are in range
    for idx in source_indices:
        if idx < 0 or idx >= len(source_bullets):
            warnings.append(ValidationWarning(
                severity="error",
                source_id=source_id,
                bullet_index=output_index,
                message=f"Source bullet index {idx} out of range (0-{len(source_bullets)-1})",
            ))
            return

    # Gather all metrics from referenced source bullets
    all_source_numbers: set[str] = set()
    for idx in source_indices:
        src = source_bullets[idx]
        # Check metrics field
        if src.metrics:
            all_source_numbers |= _extract_numbers(src.metrics)
        # Also check description for numbers
        all_source_numbers |= _extract_numbers(src.description)

    # Metric preservation: numbers in output should come from source
    output_numbers = _extract_numbers(output_text)
    novel_numbers = output_numbers - all_source_numbers
    # Filter out common non-metric numbers (single digits, years, etc.)
    novel_numbers = {n for n in novel_numbers if len(n) > 1 and not (1900 <= int(re.sub(r'%', '', n).split('.')[0]) <= 2030 if re.sub(r'%', '', n).split('.')[0].isdigit() else False)}
    if novel_numbers:
        warnings.append(ValidationWarning(
            severity="warning",
            source_id=source_id,
            bullet_index=output_index,
            message=f"Numbers in output not found in source: {novel_numbers}",
        ))
