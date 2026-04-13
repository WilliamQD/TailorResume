"""Tests for the tailored-resume validator — hallucination + style gates."""
from __future__ import annotations

import pytest

from jobplanner.bank.schema import (
    ExperienceBank,
    SelectedExperience,
    SelectedProject,
    SkillsSection,
    TailoredBullet,
    TailoredResume,
)
from jobplanner.tailor.validator import (
    BANNED_PHRASE_PATTERNS,
    PLACEHOLDER_PATTERNS,
    validate_tailored_resume,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tailored(bullet_texts: list[str]) -> TailoredResume:
    """Build a TailoredResume with the given experience-bullet texts.

    Points at exp_acme (2 source bullets) in the minimal_bank fixture. Skips
    metric-preservation problems by using sources indices [0, 1].
    """
    return TailoredResume(
        selected_experiences=[
            SelectedExperience(
                source_id="exp_acme",
                bullets=[
                    TailoredBullet(text=t, source_bullet_indices=[0])
                    for t in bullet_texts
                ],
            )
        ],
        selected_projects=[],
        skills=SkillsSection(),
        selected_coursework=[],
    )


# ---------------------------------------------------------------------------
# Banned phrases → warnings
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_text", [
    "Responsible for building the pipeline and shipping it to production.",
    "Helped with backend migration across three services.",
    "Assisted in designing a cross-team deployment workflow.",
    "Supported the platform team with incident response.",
    "Passionate about distributed systems and cloud infrastructure.",
    "A results-driven engineer delivering business outcomes.",
    "Visionary approach to API gateway design at scale.",
    "A dynamic professional tackling ambiguous problems.",
    "Thrives in a high-growth environment with shifting goals.",
    "Works well in a fast-paced environment shipping weekly.",
    "Improved performance of the batch job significantly.",
    "Enhanced efficiency of the data ingestion layer.",
])
def test_banned_phrase_triggers_warning(minimal_bank: ExperienceBank, bad_text: str):
    tailored = _tailored([bad_text])
    result = validate_tailored_resume(tailored, minimal_bank)
    # Banned phrases are warnings, so validation still passes
    assert result.passed, f"Expected banned-phrase to be a warning, not an error: {bad_text!r}"
    assert any("Banned phrase" in w.message for w in result.warnings), (
        f"Expected a banned-phrase warning for {bad_text!r}, got {[w.message for w in result.warnings]}"
    )


def test_quantified_improvements_not_flagged(minimal_bank: ExperienceBank):
    """The quantified exception: 'improved performance by 20%' should pass."""
    tailored = _tailored([
        "Improved performance by 40% via async I/O in the API gateway (10K req/s).",
        "Enhanced efficiency by 25% through query planner tuning (10K req/s).",
    ])
    result = validate_tailored_resume(tailored, minimal_bank)
    banned = [w for w in result.warnings if "Banned phrase" in w.message]
    assert not banned, f"Quantified exceptions should not be flagged: {[w.message for w in banned]}"


def test_all_banned_patterns_are_valid_regex():
    """Smoke test: every pattern must compile."""
    import re
    for pat in BANNED_PHRASE_PATTERNS + PLACEHOLDER_PATTERNS:
        re.compile(pat)


# ---------------------------------------------------------------------------
# Placeholder sentinels → errors
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_text", [
    "Built API gateway handling 10K req/s with TODO metrics later.",
    "Migrated DB schema — PLACEHOLDER for scale number.",
    "Shipped zero-downtime migration (XXX bullets to verify).",
    "Delivered TBD features ahead of schedule.",
    "Built gateway [[insert metric]] handling huge volume.",
])
def test_placeholder_triggers_error(minimal_bank: ExperienceBank, bad_text: str):
    tailored = _tailored([bad_text])
    result = validate_tailored_resume(tailored, minimal_bank)
    assert not result.passed, f"Placeholder {bad_text!r} should halt validation"
    assert any("Placeholder sentinel" in w.message for w in result.warnings)


# ---------------------------------------------------------------------------
# Duplicate bullets → error
# ---------------------------------------------------------------------------

def test_duplicate_bullets_error(minimal_bank: ExperienceBank):
    same = "Built an API gateway handling 10K req/s with p99 < 20ms latency."
    tailored = _tailored([same, same])
    result = validate_tailored_resume(tailored, minimal_bank)
    assert not result.passed
    dup_errors = [w for w in result.warnings if "Duplicate bullet" in w.message]
    assert len(dup_errors) == 1, f"Expected 1 duplicate error, got {len(dup_errors)}"


def test_duplicate_detection_normalizes_whitespace_and_case(minimal_bank: ExperienceBank):
    tailored = _tailored([
        "Built API gateway handling 10K req/s.",
        "BUILT   API  gateway handling 10K req/s.",
    ])
    result = validate_tailored_resume(tailored, minimal_bank)
    assert not result.passed
    assert any("Duplicate bullet" in w.message for w in result.warnings)


def test_duplicate_detection_across_projects_and_experiences(minimal_bank: ExperienceBank):
    """A bullet repeated across an experience and a project should still be caught."""
    dup = "Built end-to-end pipeline with MLflow tracking across 10K req/s traffic."
    tailored = TailoredResume(
        selected_experiences=[
            SelectedExperience(
                source_id="exp_acme",
                bullets=[TailoredBullet(text=dup, source_bullet_indices=[0])],
            )
        ],
        selected_projects=[
            SelectedProject(
                source_id="proj_ml",
                bullets=[TailoredBullet(text=dup, source_bullet_indices=[0])],
            )
        ],
        skills=SkillsSection(),
        selected_coursework=[],
    )
    result = validate_tailored_resume(tailored, minimal_bank)
    assert not result.passed
    assert any("Duplicate bullet" in w.message for w in result.warnings)


# ---------------------------------------------------------------------------
# Clean resume passes
# ---------------------------------------------------------------------------

def test_clean_resume_has_no_style_warnings(minimal_bank: ExperienceBank):
    tailored = _tailored([
        "Built Python FastAPI gateway handling 10K req/s with p99 < 20ms.",
        "Migrated PostgreSQL schema to multi-tenant model with 0 downtime migration.",
    ])
    result = validate_tailored_resume(tailored, minimal_bank)
    assert result.passed
    style = [w for w in result.warnings
             if "Banned phrase" in w.message
             or "Placeholder sentinel" in w.message
             or "Duplicate bullet" in w.message]
    assert not style, f"Clean resume produced style warnings: {[w.message for w in style]}"
