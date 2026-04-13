"""Post-tailor critic/improve pass — rewrites weak bullets and flags thin bank entries."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from jobplanner.bank.schema import ExperienceBank, ParsedJD, TailoredResume
from jobplanner.llm.base import LLMClient
from jobplanner.tailor.enrichment import EnrichedContext


CRITIC_SYSTEM = """\
You are a senior resume reviewer and career coach with 15 years of experience
helping candidates land interviews at top companies. You have deep expertise in
what makes resumes succeed — and fail — with both automated ATS screening and
human recruiters.

You will review a tailored resume and improve it. Your job is to raise the quality
of the language and framing, not to change the facts or add new experiences.

ABSOLUTE RULES:
1. Preserve ALL source citations — source_id and source_bullet_indices must not change.
2. Do NOT add experiences, projects, or skills not present in the original resume.
3. Do NOT add metrics or numbers not present in the original bullet text.
4. You may rewrite bullet TEXT for clarity, impact, and keyword alignment.
5. You may reorder bullets within an experience (put most impactful first).
6. You may adjust skill section labels and skill ordering.
7. You may trim coursework to only the most relevant courses.

QUALITY CRITERIA — evaluate every bullet in two passes.

## Pass 1: Impact & alignment
1. IMPACT-FIRST: Does the bullet lead with the result/outcome, not the task performed?
2. SPECIFICITY: Are there concrete numbers, tools, or scale indicators?
3. ACTION VERB: Does it start with a strong verb (Built, Designed, Reduced) not a weak one (Helped, Worked on)?
4. JD ALIGNMENT: Does the language mirror the JD's vocabulary and priorities?
5. LENGTH: Is it ~130–160 characters? Too short wastes space. Too long wraps awkwardly.

## Pass 2: Humanization (do this AFTER pass 1, on the rewritten bullets)
6. NO BUZZWORDS / FLUFF: strip filler phrases. Reject specifically:
   "leveraged cutting-edge", "spearheaded innovative", "synergize",
   "passionate about", "results-driven", "fast-paced environment",
   "dynamic professional", "visionary", "responsible for", "helped with",
   "assisted in", "thrives in", "improved performance" (unquantified).
7. NO REPEATED SYNTAX: across any 3+ consecutive bullets within a single
   experience or project, the opening verb AND sentence shape must vary.
   Reject "Built X that... Built Y that... Built Z that..." patterns —
   reshape at least one of them.
8. HUMAN VOICE: sounds like a real engineer wrote it, not a template.
   No generic AI patterns. No sentences that could apply to any candidate.

## Pass 3: Plain-language rewrite (MANDATORY for EVERY bullet)
9. Read each bullet in your head as if you were a non-technical recruiter
   with 7 seconds per resume. If you would not grasp it on a single pass,
   REWRITE it in plain English.
10. Reject JARGON CLUSTERS — 3+ technical modifiers stacked on one noun.
    Example to fix:
      BAD: "Authored automated null-rate, distribution, and temporal-
            consistency tests plus documentation"
      GOOD: "Wrote automated data-quality checks and documentation that
             cut new-hire onboarding from weeks to days"
    Replace the cluster with the plain-English category the reviewer
    already knows ("data-quality checks", "validation tests").
11. Reject these weak/pretentious verbs and replace them with simple ones:
      authored   → wrote
      spearheaded→ led
      orchestrated → ran / built / coordinated
      leveraged  → used
      engineered → built / designed (unless literally an engineer)
      facilitated→ ran / led
      enabled    → let / helped
12. Enforce the LINE-FILL RULE (MEASURED against this template):
    each bullet must EITHER be ≤ 105 chars (one printed line) OR ≥ 185
    chars (two full printed lines). NOTHING in the 106-184 forbidden zone
    — those wrap with 2-5 orphan words on line 2 and waste page space.
    If a bullet is in the forbidden zone, either TRIM it to ≤ 105 chars
    or EXTEND it to ≥ 185 chars by adding ONE concrete detail (metric,
    tool, scope, outcome). Never pad with vague words. A 117-char bullet
    ("...and helped new analysts ramp up faster.") is a real failure from
    a prior run — "faster." orphaned on line 2. Count characters.
13. "What and why" test: every bullet must answer WHAT you did and WHY it
    mattered to the business — in plain words. If you cannot say why it
    mattered, cut the bullet or flag the bank entry as thin.

BANK FEEDBACK — for bullets that are weak because the SOURCE is thin:
Flag them as BankSuggestion entries. Don't try to fix what you don't have data for —
instead tell the user what to add to their experience bank.

OUTPUT FORMAT:
Return a JSON object with:
- improved_resume: the full TailoredResume JSON (same schema, improved text)
- bank_suggestions: list of {source_id, bullet_index, issue, suggestion, priority}
  where issue is one of: thin_description | missing_metrics | vague_impact | missing_tech_detail
  and priority is: high | medium | low
- summary: 1–2 sentences describing what you changed and why
"""


def _format_resume_for_critic(
    tailored: TailoredResume,
    bank: ExperienceBank,
    jd: ParsedJD,
    enriched: EnrichedContext | None,
) -> str:
    """Build the user message for the critic call."""
    lines = ["## Job Description\n"]
    lines.append(f"**Role:** {jd.title} at {jd.company} ({jd.role_type})")
    lines.append(f"**Required skills:** {', '.join(jd.required_skills)}")
    if jd.key_responsibilities:
        lines.append(f"**Key responsibilities:** {'; '.join(jd.key_responsibilities[:3])}\n")
    else:
        lines.append("")

    if enriched and enriched.guidelines_excerpt:
        lines.append("## Resume Writing Guidelines\n")
        lines.append(enriched.guidelines_excerpt[:3000])  # cap to avoid token bloat
        lines.append("")

    if enriched and enriched.exemplary_bullets:
        lines.append("## Exemplary Bullets (calibration)\n")
        lines.append(enriched.exemplary_bullets[:2000])
        lines.append("")

    if enriched and enriched.structure_template:
        lines.append("## Structure Strategy\n")
        lines.append(enriched.structure_template[:1000])
        lines.append("")

    lines.append("## Current Tailored Resume (to be improved)\n")
    lines.append(tailored.model_dump_json(indent=2))

    return "\n".join(lines)


@dataclass
class BankSuggestion:
    source_id: str
    bullet_index: int
    issue: str          # thin_description | missing_metrics | vague_impact | missing_tech_detail
    suggestion: str
    priority: str       # high | medium | low


@dataclass
class CriticResult:
    improved_resume: TailoredResume
    bank_suggestions: list[BankSuggestion] = field(default_factory=list)
    summary: str = ""


class _BankSuggestionModel(BaseModel):
    source_id: str
    bullet_index: int
    issue: str
    suggestion: str
    priority: str


class _CriticOutputModel(BaseModel):
    improved_resume: TailoredResume
    bank_suggestions: list[_BankSuggestionModel] = Field(default_factory=list)
    summary: str = ""


def run_critic(
    client: LLMClient,
    tailored: TailoredResume,
    bank: ExperienceBank,
    jd: ParsedJD,
    enriched: EnrichedContext | None = None,
) -> CriticResult:
    """Run the critic pass — returns an improved TailoredResume + bank suggestions."""
    user_msg = _format_resume_for_critic(tailored, bank, jd, enriched)

    output = client.complete(
        system=CRITIC_SYSTEM,
        user=user_msg,
        response_model=_CriticOutputModel,
    )

    suggestions = [
        BankSuggestion(
            source_id=s.source_id,
            bullet_index=s.bullet_index,
            issue=s.issue,
            suggestion=s.suggestion,
            priority=s.priority,
        )
        for s in output.bank_suggestions
    ]

    return CriticResult(
        improved_resume=output.improved_resume,
        bank_suggestions=suggestions,
        summary=output.summary,
    )
