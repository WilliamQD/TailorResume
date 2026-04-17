"""Programmatic line-fill enforcement — the canonical orphan defense.

The LLM cannot reliably count characters. Prior prompt-level rules (tailor
system prompt, critic Pass 3, LaTeX `\\emergencystretch`) mitigate only the
shallowest overflows. This module measures every tailored bullet in Python,
flags anything in the 106-184 char "forbidden zone", and issues a single
batched rewrite call to the LLM with per-bullet targets and direction. Runs
after the critic, before PDF render — it is the last gate on length.

Cost profile:
- 0 LLM calls when every bullet is already compliant.
- 1 batched LLM call when any bullets are flagged (all flagged bullets fit
  in one request — never per-bullet calls).
- At most `max_rounds` (default 2) batched calls in the worst case.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from jobplanner.bank.schema import (
    Bullet,
    ExperienceBank,
    TailoredResume,
)
from jobplanner.llm.base import LLMClient


# Measured against the template (10pt Latin Modern, 7.3in text width,
# 1.15em itemize indent). See CLAUDE.md "Line-fill rule".
ONE_LINE_MAX = 105
FORBIDDEN_MIN = 106
FORBIDDEN_MAX = 184
TWO_LINE_MIN = 185
# When rewriting, aim a few chars past each boundary for safety margin.
TRIM_TARGET = 105
EXTEND_TARGET = 190
# Midpoint of the forbidden zone — below this we trim toward 105,
# at or above we extend toward 190.
TRIM_THRESHOLD = 145


LENGTH_GATE_SYSTEM = """\
You are a resume-bullet length editor.

Every bullet given to you is in the "forbidden zone" (106-184 characters) —
it wraps to two lines with a short dangling tail, wasting page space. You
rewrite each one to either:
  - TRIM to ≤ 105 characters (one clean printed line), OR
  - EXTEND to ≥ 190 characters (two nearly-full printed lines)

The target (TRIM or EXTEND) is specified per bullet. Obey it.

Rules:
1. Preserve every fact and metric from the source notes — never invent.
2. TRIM = cut filler ("and helped...", "in order to...", hedges), shorten
   verbs, drop the least-important detail. Never pad; never invent.
3. EXTEND = add ONE concrete detail already present in the source notes
   (a metric, tool, scope indicator, or outcome). Never pad with vague
   words like "successfully", "effectively", "strategically".
4. Keep plain HR-friendly English. No jargon clusters. Simple verbs.
5. Do not change the overall meaning or claim of the bullet.

Output JSON: {"rewrites": [{"id": "...", "new_text": "..."}, ...]} —
one entry per input bullet. Each new_text must hit its target band.
"""


@dataclass(frozen=True)
class _BulletLoc:
    """Pointer to one bullet in a TailoredResume."""

    section: str  # "experience" or "project"
    section_idx: int
    bullet_idx: int
    source_id: str
    text: str
    source_bullet_indices: list[int]

    @property
    def id(self) -> str:
        return f"{self.section}_{self.section_idx}_{self.bullet_idx}"


class _RewrittenBullet(BaseModel):
    id: str
    new_text: str


class _LengthGateOutput(BaseModel):
    rewrites: list[_RewrittenBullet]


def _enumerate_bullets(resume: TailoredResume) -> list[_BulletLoc]:
    locs: list[_BulletLoc] = []
    for ei, se in enumerate(resume.selected_experiences):
        for bi, b in enumerate(se.bullets):
            locs.append(_BulletLoc(
                section="experience",
                section_idx=ei,
                bullet_idx=bi,
                source_id=se.source_id,
                text=b.text,
                source_bullet_indices=list(b.source_bullet_indices),
            ))
    for pi, sp in enumerate(resume.selected_projects):
        for bi, b in enumerate(sp.bullets):
            locs.append(_BulletLoc(
                section="project",
                section_idx=pi,
                bullet_idx=bi,
                source_id=sp.source_id,
                text=b.text,
                source_bullet_indices=list(b.source_bullet_indices),
            ))
    return locs


def _apply_rewrites(resume: TailoredResume, rewrites: dict[str, str]) -> None:
    if not rewrites:
        return
    for ei, se in enumerate(resume.selected_experiences):
        for bi, b in enumerate(se.bullets):
            key = f"experience_{ei}_{bi}"
            if key in rewrites:
                b.text = rewrites[key]
    for pi, sp in enumerate(resume.selected_projects):
        for bi, b in enumerate(sp.bullets):
            key = f"project_{pi}_{bi}"
            if key in rewrites:
                b.text = rewrites[key]


def _source_facts(loc: _BulletLoc, bank: ExperienceBank) -> str:
    """Return just the source notes for this bullet's cited indices."""
    if loc.section == "experience":
        entry = bank.get_experience(loc.source_id)
    else:
        entry = bank.get_project(loc.source_id)
    if entry is None:
        return "(source not found)"

    parts: list[str] = []
    for idx in loc.source_bullet_indices:
        if not 0 <= idx < len(entry.bullets):
            continue
        src: Bullet = entry.bullets[idx]
        parts.append(f"- {src.description}")
        if src.metrics:
            parts.append(f"  metrics: {src.metrics}")
        if src.tech_stack:
            parts.append(f"  tech: {', '.join(src.tech_stack)}")
    return "\n".join(parts) if parts else "(no source bullets cited)"


def is_forbidden(text: str) -> bool:
    """True iff `text` is in the 106-184 forbidden zone."""
    return FORBIDDEN_MIN <= len(text) <= FORBIDDEN_MAX


def direction_for(current_len: int) -> tuple[str, int]:
    """Return (direction_label, target_char_count) for a forbidden-zone bullet."""
    if current_len < TRIM_THRESHOLD:
        return ("TRIM", TRIM_TARGET)
    return ("EXTEND", EXTEND_TARGET)


def _distance_to_safe(text_len: int) -> int:
    """0 if already safe, else min distance to either safe boundary."""
    if text_len <= ONE_LINE_MAX or text_len >= TWO_LINE_MIN:
        return 0
    return min(text_len - ONE_LINE_MAX, TWO_LINE_MIN - text_len)


def _build_user_message(
    flagged: list[_BulletLoc], bank: ExperienceBank
) -> str:
    sections: list[str] = []
    for loc in flagged:
        current_len = len(loc.text)
        direction, _target = direction_for(current_len)
        target_str = "≤ 105" if direction == "TRIM" else "≥ 190"
        sections.append(
            f"### id: {loc.id}\n"
            f"Current ({current_len} chars): {loc.text}\n"
            f"Direction: {direction} — target {target_str} chars\n"
            f"Source notes:\n{_source_facts(loc, bank)}"
        )
    return (
        "Rewrite each bullet to its target length band.\n\n"
        + "\n\n---\n\n".join(sections)
    )


def enforce_line_fill(
    resume: TailoredResume,
    bank: ExperienceBank,
    llm: LLMClient,
    max_rounds: int = 2,
) -> tuple[TailoredResume, list[str]]:
    """Gate every bullet against the 106-184 forbidden zone.

    Flagged bullets are rewritten via a single batched LLM call per round
    (at most `max_rounds` rounds). If a bullet is still in the forbidden
    zone after all rounds, revert it to whichever attempt (original or any
    rewrite) landed closest to a safe boundary, and log a warning.

    Zero LLM calls on clean inputs. Mutates `resume` in place and also
    returns it for convenience.
    """
    warnings: list[str] = []

    # Track the best (closest-to-safe) version of each bullet across all
    # attempts. If the model makes a bullet worse on a later round, we
    # revert to the best version at the end.
    best_text: dict[str, str] = {loc.id: loc.text for loc in _enumerate_bullets(resume)}

    for round_num in range(max_rounds):
        flagged = [loc for loc in _enumerate_bullets(resume) if is_forbidden(loc.text)]
        if not flagged:
            break

        # Record current state against best-known before attempting rewrite.
        for loc in _enumerate_bullets(resume):
            if _distance_to_safe(len(loc.text)) < _distance_to_safe(len(best_text[loc.id])):
                best_text[loc.id] = loc.text

        user_msg = _build_user_message(flagged, bank)
        try:
            output = llm.complete(
                system=LENGTH_GATE_SYSTEM,
                user=user_msg,
                response_model=_LengthGateOutput,
            )
        except Exception as exc:
            warnings.append(f"Length gate round {round_num + 1} LLM error: {exc}")
            break

        rewrites = {r.id: r.new_text for r in output.rewrites}
        _apply_rewrites(resume, rewrites)

    # Final best-tracker update after the last round.
    for loc in _enumerate_bullets(resume):
        if _distance_to_safe(len(loc.text)) < _distance_to_safe(len(best_text[loc.id])):
            best_text[loc.id] = loc.text

    # Revert any still-forbidden bullet to its best-known version.
    revert_map: dict[str, str] = {}
    for loc in _enumerate_bullets(resume):
        if is_forbidden(loc.text) and best_text[loc.id] != loc.text:
            revert_map[loc.id] = best_text[loc.id]
    _apply_rewrites(resume, revert_map)

    # Emit warnings for anything still in the forbidden zone.
    for loc in _enumerate_bullets(resume):
        if is_forbidden(loc.text):
            warnings.append(
                f"{loc.source_id}[{loc.bullet_idx}] stayed at {len(loc.text)} chars "
                f"(forbidden zone {FORBIDDEN_MIN}-{FORBIDDEN_MAX})"
            )

    return resume, warnings
