"""Tests for the programmatic line-fill enforcement gate.

Uses a FakeLLM that returns pre-canned rewrites keyed by bullet id, so we
can exercise the retry loop, batching, and fallback logic deterministically
without any real API calls.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from jobplanner.bank.schema import (
    Bullet,
    Experience,
    ExperienceBank,
    Meta,
    Project,
    SelectedExperience,
    SelectedProject,
    TailoredBullet,
    TailoredResume,
)
from jobplanner.tailor.length_gate import (
    EXTEND_TARGET,
    FORBIDDEN_MAX,
    FORBIDDEN_MIN,
    ONE_LINE_MAX,
    TRIM_TARGET,
    TWO_LINE_MIN,
    direction_for,
    enforce_line_fill,
    is_forbidden,
)

T = TypeVar("T", bound=BaseModel)


# ---- helpers ---------------------------------------------------------------


class FakeLLM:
    """Deterministic LLM stub.

    `responses` maps bullet_id → new_text. On each call, returns whichever
    flagged bullet ids appear in the incoming user message. Tracks call
    count so tests can assert batching and retry behavior.
    """

    def __init__(self, responses: dict[str, str] | list[dict[str, str]]):
        # responses may be a single dict (same for every round) or a list
        # indexed by round (responses[0] for round 1, etc.).
        self._per_round = responses if isinstance(responses, list) else [responses]
        self.calls: list[str] = []

    def complete(self, system: str, user: str, response_model: type[T]) -> T:
        from jobplanner.tailor.length_gate import _LengthGateOutput, _RewrittenBullet

        assert response_model is _LengthGateOutput
        round_idx = min(len(self.calls), len(self._per_round) - 1)
        table = self._per_round[round_idx]
        self.calls.append(user)

        rewrites: list[_RewrittenBullet] = []
        for bullet_id, new_text in table.items():
            if f"id: {bullet_id}" in user:
                rewrites.append(_RewrittenBullet(id=bullet_id, new_text=new_text))
        return _LengthGateOutput(rewrites=rewrites)

    def complete_text(self, system: str, user: str) -> str:
        raise NotImplementedError


def _make_bank() -> ExperienceBank:
    return ExperienceBank(
        meta=Meta(name="Test User"),
        experience=[
            Experience(
                id="acme",
                organization="Acme",
                role="Engineer",
                dates="2024",
                bullets=[
                    Bullet(
                        description="Built a Python RAG pipeline over 10-Ks, earnings calls, and patents",
                        tech_stack=["Python", "LangChain", "Pinecone"],
                        metrics="6 namespaces, A100 GPUs",
                    ),
                    Bullet(
                        description="Added reranking and Pydantic validation to improve retrieval precision",
                        tech_stack=["Pydantic"],
                        metrics="",
                    ),
                ],
            ),
        ],
        projects=[
            Project(
                id="side_app",
                name="Side App",
                bullets=[
                    Bullet(
                        description="Built a Next.js dashboard for live market data",
                        tech_stack=["Next.js", "TypeScript"],
                    ),
                ],
            ),
        ],
    )


def _make_resume(bullets_by_exp: list[list[str]], project_bullets: list[str] | None = None) -> TailoredResume:
    selected_experiences = [
        SelectedExperience(
            source_id="acme",
            bullets=[TailoredBullet(source_bullet_indices=[0], text=t) for t in bullets],
        )
        for bullets in bullets_by_exp
    ]
    selected_projects = []
    if project_bullets:
        selected_projects.append(SelectedProject(
            source_id="side_app",
            bullets=[TailoredBullet(source_bullet_indices=[0], text=t) for t in project_bullets],
        ))
    return TailoredResume(
        selected_experiences=selected_experiences,
        selected_projects=selected_projects,
    )


def _text_of_length(n: int, prefix: str = "Built a Python RAG pipeline") -> str:
    """Produce text of exactly n chars by padding."""
    if len(prefix) >= n:
        return prefix[:n]
    return prefix + " x" * ((n - len(prefix)) // 2) + " ." * ((n - len(prefix)) % 2)


# ---- unit tests on helpers -------------------------------------------------


def test_is_forbidden_boundaries() -> None:
    assert not is_forbidden("x" * 105)
    assert is_forbidden("x" * 106)
    assert is_forbidden("x" * 184)
    assert not is_forbidden("x" * 185)


def test_direction_trim_vs_extend() -> None:
    d_lo, t_lo = direction_for(120)
    assert d_lo == "TRIM"
    assert t_lo == TRIM_TARGET
    d_hi, t_hi = direction_for(170)
    assert d_hi == "EXTEND"
    assert t_hi == EXTEND_TARGET


# ---- behavior tests --------------------------------------------------------


def test_clean_resume_triggers_no_llm_calls() -> None:
    """Every bullet is already in a safe band → zero LLM calls."""
    short = _text_of_length(90)
    long = _text_of_length(200)
    resume = _make_resume([[short, long]])
    bank = _make_bank()
    llm = FakeLLM({})

    _, warnings = enforce_line_fill(resume, bank, llm)

    assert llm.calls == []
    assert warnings == []
    # Bullets unchanged
    assert resume.selected_experiences[0].bullets[0].text == short
    assert resume.selected_experiences[0].bullets[1].text == long


def test_forbidden_bullets_fixed_in_one_round() -> None:
    """3 forbidden-zone bullets → 1 batched LLM call, all fixed."""
    bad1 = _text_of_length(120)
    bad2 = _text_of_length(130)
    bad3 = _text_of_length(170)
    resume = _make_resume([[bad1, bad2], [bad3]])
    bank = _make_bank()

    # Make Experience index 1 exist in bank for the second SelectedExperience.
    # (Our bank has only one experience, but we can cite "acme" twice.)
    resume.selected_experiences[1].source_id = "acme"

    good_short = _text_of_length(100)
    good_long = _text_of_length(195)
    llm = FakeLLM({
        "experience_0_0": good_short,
        "experience_0_1": good_short,
        "experience_1_0": good_long,
    })

    _, warnings = enforce_line_fill(resume, bank, llm)

    assert len(llm.calls) == 1
    assert warnings == []
    assert resume.selected_experiences[0].bullets[0].text == good_short
    assert resume.selected_experiences[0].bullets[1].text == good_short
    assert resume.selected_experiences[1].bullets[0].text == good_long


def test_retry_loop_fires_when_round_one_misses() -> None:
    """Round 1 returns still-forbidden text → round 2 fires on the remainder."""
    bad = _text_of_length(130)
    resume = _make_resume([[bad]])
    bank = _make_bank()

    still_bad = _text_of_length(140)  # still in forbidden zone
    fixed = _text_of_length(100)
    llm = FakeLLM([
        {"experience_0_0": still_bad},  # round 1: makes it different but still bad
        {"experience_0_0": fixed},       # round 2: actually fixes it
    ])

    _, warnings = enforce_line_fill(resume, bank, llm)

    assert len(llm.calls) == 2
    assert warnings == []
    assert resume.selected_experiences[0].bullets[0].text == fixed


def test_fallback_picks_closest_to_boundary_after_max_rounds() -> None:
    """After max_rounds with no success, revert each bullet to the closest-to-safe
    version seen across all attempts (original or any rewrite)."""
    # Original is 140 chars (15 past 105 boundary; 45 short of 185)
    original = _text_of_length(140)
    resume = _make_resume([[original]])
    bank = _make_bank()

    round1 = _text_of_length(120)  # distance 15 to 105 — tied with original
    round2 = _text_of_length(110)  # distance 5 to 105 — better than original
    llm = FakeLLM([
        {"experience_0_0": round1},
        {"experience_0_0": round2},
    ])

    _, warnings = enforce_line_fill(resume, bank, llm)

    assert len(llm.calls) == 2
    # All attempts landed in forbidden zone → warning logged
    assert len(warnings) == 1
    assert "acme" in warnings[0]
    # Final text is the closest-to-boundary version (round 2 at 110)
    assert resume.selected_experiences[0].bullets[0].text == round2


def test_fallback_keeps_original_when_rewrites_are_worse() -> None:
    """If every rewrite is further from safe than the original, revert to original."""
    original = _text_of_length(110)  # 5 away from 105
    resume = _make_resume([[original]])
    bank = _make_bank()

    worse1 = _text_of_length(150)  # 40 away from either boundary (35 from 185... wait: min(150-105, 185-150) = min(45, 35) = 35)
    worse2 = _text_of_length(160)  # min(55, 25) = 25 — wait, 25 < 5? No, we want both to be WORSE than 5.
    # Rebuild: original at 110 has distance min(110-105, 185-110) = min(5, 75) = 5.
    # worse1 at 120: distance min(15, 65) = 15 → worse than 5. Good.
    worse1 = _text_of_length(120)
    worse2 = _text_of_length(130)
    llm = FakeLLM([
        {"experience_0_0": worse1},
        {"experience_0_0": worse2},
    ])

    _, warnings = enforce_line_fill(resume, bank, llm)

    assert len(warnings) == 1
    # Original was closest to boundary — should be restored.
    assert resume.selected_experiences[0].bullets[0].text == original


def test_second_round_only_processes_still_bad_bullets() -> None:
    """Round 1 fixes bullet A but not B → round 2 user msg should only include B."""
    bad_a = _text_of_length(120)
    bad_b = _text_of_length(170)
    resume = _make_resume([[bad_a, bad_b]])
    bank = _make_bank()

    good_a = _text_of_length(100)
    still_bad_b = _text_of_length(160)
    fixed_b = _text_of_length(195)

    llm = FakeLLM([
        {"experience_0_0": good_a, "experience_0_1": still_bad_b},
        {"experience_0_1": fixed_b},
    ])

    _, warnings = enforce_line_fill(resume, bank, llm)

    assert len(llm.calls) == 2
    # Round 2 message should NOT reference experience_0_0 (already safe).
    assert "id: experience_0_0" not in llm.calls[1]
    assert "id: experience_0_1" in llm.calls[1]
    assert warnings == []
    assert resume.selected_experiences[0].bullets[0].text == good_a
    assert resume.selected_experiences[0].bullets[1].text == fixed_b


def test_projects_are_gated_too() -> None:
    """Project bullets also get checked and rewritten."""
    bad_proj = _text_of_length(135)
    resume = _make_resume([[_text_of_length(100)]], project_bullets=[bad_proj])
    bank = _make_bank()

    fixed = _text_of_length(200)
    llm = FakeLLM({"project_0_0": fixed})

    _, warnings = enforce_line_fill(resume, bank, llm)

    assert len(llm.calls) == 1
    assert warnings == []
    assert resume.selected_projects[0].bullets[0].text == fixed


def test_llm_exception_breaks_loop_with_warning() -> None:
    """LLM error is caught, warning logged, loop exits cleanly."""

    class ExplodingLLM:
        def complete(self, system, user, response_model):
            raise RuntimeError("boom")

        def complete_text(self, system, user):
            raise NotImplementedError

    bad = _text_of_length(130)
    resume = _make_resume([[bad]])
    bank = _make_bank()

    _, warnings = enforce_line_fill(resume, bank, ExplodingLLM())

    assert any("boom" in w for w in warnings)
    # Bullet preserved as-is (original)
    assert resume.selected_experiences[0].bullets[0].text == bad
    # And the persistent forbidden-zone warning is also logged.
    assert any("forbidden zone" in w for w in warnings)
