"""Tests for the critic module."""
from __future__ import annotations

from jobplanner.checker.critic import BankSuggestion, CriticResult
from jobplanner.bank.schema import (
    TailoredResume, SelectedExperience, SelectedProject, TailoredBullet, SkillsSection
)


def _make_tailored() -> TailoredResume:
    return TailoredResume(
        selected_experiences=[
            SelectedExperience(
                source_id="exp_acme",
                bullets=[
                    TailoredBullet(source_bullet_indices=[0], text="Built an API gateway"),
                    TailoredBullet(source_bullet_indices=[1], text="Migrated database schema"),
                ],
            )
        ],
        selected_projects=[
            SelectedProject(
                source_id="proj_ml",
                bullets=[TailoredBullet(source_bullet_indices=[0], text="End-to-end ML pipeline")],
            )
        ],
        skills=SkillsSection(line1_label="Languages", line1=["Python", "SQL"]),
    )


def test_bank_suggestion_fields():
    s = BankSuggestion(
        source_id="exp_acme",
        bullet_index=0,
        issue="missing_metrics",
        suggestion="Add latency numbers",
        priority="high",
    )
    assert s.source_id == "exp_acme"
    assert s.priority == "high"


def test_critic_result_fields():
    tailored = _make_tailored()
    result = CriticResult(
        improved_resume=tailored,
        bank_suggestions=[],
        summary="No major changes",
    )
    assert result.improved_resume is tailored
    assert result.bank_suggestions == []
    assert result.summary == "No major changes"


def test_critic_result_preserves_source_citations():
    """CriticResult.improved_resume must have the same source_ids as input."""
    tailored = _make_tailored()
    result = CriticResult(improved_resume=tailored, bank_suggestions=[], summary="")
    exp_ids = [e.source_id for e in result.improved_resume.selected_experiences]
    assert "exp_acme" in exp_ids
