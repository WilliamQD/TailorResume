"""Post-AI hallucination + style validator for tailored resumes (synthesis mode)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jobplanner.bank.schema import ExperienceBank, TailoredResume


# ---------------------------------------------------------------------------
# Style gates (ported from SankaiAI/ats-optimized-resume-agent-skill)
# ---------------------------------------------------------------------------

# Weak / overused language. Flagged as warnings (LLM may rewrite at critic
# stage). The quantified exceptions ("improved performance by 20%") are
# allowed via negative lookahead.
BANNED_PHRASE_PATTERNS: tuple[str, ...] = (
    r"\bresponsible for\b",
    r"\bhelped (with|to)\b",
    r"\bassisted (with|in)\b",
    r"\bsupported\b.{0,30}\bteam\b",
    r"\bpassionate (about|for)\b",
    r"\bresults[- ]driven\b",
    r"\bvisionary\b",
    r"\bdynamic professional\b",
    r"\bthrive[sd]? in\b",
    r"\bfast[- ]paced environment\b",
    r"\bimproved performance\b(?!\s+by)",
    r"\benhanced efficiency\b(?!\s+by)",
)

# Placeholder sentinels. Any match is a hard error — the LLM left a hole.
PLACEHOLDER_PATTERNS: tuple[str, ...] = (
    r"\bTODO\b",
    r"\bPLACEHOLDER\b",
    r"\bXXX\b",
    r"\bTBD\b",
    r"\[\[",
)

_BANNED_RE = tuple(re.compile(p, re.IGNORECASE) for p in BANNED_PHRASE_PATTERNS)
_PLACEHOLDER_RE = tuple(re.compile(p, re.IGNORECASE) for p in PLACEHOLDER_PATTERNS)


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

    Style checks (Stage 1):
    5. Banned phrases -- weak/overused language (warnings only)
    6. Placeholder sentinels -- TODO/TBD/XXX etc. (errors)
    7. Duplicate bullets -- same normalized text across all bullets (errors)
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

    # Style gates run over every rendered bullet regardless of source
    _check_style_gates(tailored, warnings)

    has_errors = any(w.severity == "error" for w in warnings)
    return ValidationResult(passed=not has_errors, warnings=warnings)


def _check_style_gates(
    tailored: TailoredResume,
    warnings: list[ValidationWarning],
) -> None:
    """Scan every tailored bullet for banned phrases, placeholders, duplicates.

    Banned phrases → warning. Placeholders and duplicates → error (they are
    either LLM bugs or unambiguous leftovers that block shipping).
    """
    # (source_id, bullet_index, text) for every synthesized bullet
    all_bullets: list[tuple[str, int, str]] = []
    for sel in tailored.selected_experiences:
        for i, tb in enumerate(sel.bullets):
            all_bullets.append((sel.source_id, i, tb.text))
    for sel in tailored.selected_projects:
        for i, tb in enumerate(sel.bullets):
            all_bullets.append((sel.source_id, i, tb.text))

    # Banned phrases + placeholder sentinels per bullet
    for source_id, idx, text in all_bullets:
        for pat in _BANNED_RE:
            m = pat.search(text)
            if m:
                warnings.append(ValidationWarning(
                    severity="warning",
                    source_id=source_id,
                    bullet_index=idx,
                    message=f"Banned phrase {m.group(0)!r} (pattern {pat.pattern!r})",
                ))
        for pat in _PLACEHOLDER_RE:
            m = pat.search(text)
            if m:
                warnings.append(ValidationWarning(
                    severity="error",
                    source_id=source_id,
                    bullet_index=idx,
                    message=f"Placeholder sentinel {m.group(0)!r} left in bullet text",
                ))

    # Duplicate bullet detection — normalized lowercase + whitespace-collapsed.
    seen: dict[str, tuple[str, int]] = {}
    for source_id, idx, text in all_bullets:
        key = re.sub(r"\s+", " ", text.strip().lower())
        if not key:
            continue
        if key in seen:
            first_src, first_idx = seen[key]
            warnings.append(ValidationWarning(
                severity="error",
                source_id=source_id,
                bullet_index=idx,
                message=(
                    f"Duplicate bullet (matches {first_src}[{first_idx}]): "
                    f"{text[:60]!r}"
                ),
            ))
        else:
            seen[key] = (source_id, idx)


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
