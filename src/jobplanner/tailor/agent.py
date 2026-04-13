"""Resume tailoring agent — synthesizes bullets from the bank."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from jobplanner.tailor.enrichment import EnrichedContext

from jobplanner.bank.schema import (
    ExperienceBank,
    ParsedJD,
    TailoredResume,
)
from jobplanner.config import Settings
from jobplanner.llm.base import LLMClient
from jobplanner.tailor.prompts import TAILOR_SYSTEM_PROMPT, build_tailor_user_prompt

def _bank_to_yaml_snippet(
    bank: ExperienceBank,
    jd: ParsedJD,
    exclude_roles: list[str] | None = None,
) -> str:
    """Serialize the bank to a compact YAML string for the prompt.

    Filtering strategy:
    - ALL experiences are always included (typically only 3, all relevant)
    - Projects: include if tags/skills overlap OR if it's an anchor project
    - Strips `context` field from bullets (saves ~200 tokens)
    - Omits global `skills` section (redundant with per-bullet skills)
    - Includes inferred_skills for the skills section
    - Hard-excludes any experience/project whose id is in `exclude_roles`
    """
    jd_terms = {s.lower() for s in jd.required_skills + jd.preferred_skills + jd.keywords}
    jd_terms.add(jd.role_type)
    excluded = set(exclude_roles or [])

    def _is_relevant(tags: list[str], bullets: list) -> bool:
        tag_set = {t.lower() for t in tags}
        if tag_set & jd_terms:
            return True
        for b in bullets:
            if {s.lower() for s in b.skills} & jd_terms:
                return True
            if {s.lower() for s in b.tech_stack} & jd_terms:
                return True
        return False

    def _serialize_bullets(bullets: list) -> list[dict]:
        """Serialize bullets without the context field to save tokens."""
        result = []
        for b in bullets:
            entry: dict = {"description": b.description}
            if b.tech_stack:
                entry["tech_stack"] = b.tech_stack
            if b.skills:
                entry["skills"] = b.skills
            if b.metrics:
                entry["metrics"] = b.metrics
            result.append(entry)
        return result

    filtered: dict = {
        "education": [e.model_dump() for e in bank.education],
        "experience": [],
        "projects": [],
    }

    # Always include all experiences (unless excluded)
    for exp in bank.experience:
        if exp.id in excluded:
            continue
        d = {
            "id": exp.id,
            "organization": exp.organization,
            "role": exp.role,
            "location": exp.location,
            "dates": exp.dates,
            "tags": exp.tags,
            "bullets": _serialize_bullets(exp.bullets),
        }
        filtered["experience"].append(d)

    # Include relevant projects + anchor projects (anchor: true in bank).
    # Excluded ids are always dropped, even if anchored.
    anchor_ids = {p.id for p in bank.projects if p.anchor}
    for proj in bank.projects:
        if proj.id in excluded:
            continue
        if _is_relevant(proj.tags, proj.bullets) or proj.id in anchor_ids:
            d = {
                "id": proj.id,
                "name": proj.name,
                "dates": proj.dates,
                "url": proj.url,
                "tags": proj.tags,
                "bullets": _serialize_bullets(proj.bullets),
            }
            filtered["projects"].append(d)

    # If filtering was too aggressive, include all non-excluded projects
    if not filtered["projects"]:
        for proj in bank.projects:
            if proj.id in excluded:
                continue
            d = {
                "id": proj.id,
                "name": proj.name,
                "dates": proj.dates,
                "url": proj.url,
                "tags": proj.tags,
                "bullets": _serialize_bullets(proj.bullets),
            }
            filtered["projects"].append(d)

    # Include inferred skills (for the skills section)
    if bank.inferred_skills:
        filtered["inferred_skills"] = [
            {"name": s.name, "basis": s.basis, "confidence": s.confidence}
            for s in bank.inferred_skills
        ]

    return yaml.dump(filtered, default_flow_style=False, allow_unicode=True, width=120)


def _format_jd_summary(jd: ParsedJD) -> str:
    """Format the parsed JD as a readable summary for the prompt."""
    lines = [
        f"**Title:** {jd.title}",
        f"**Company:** {jd.company}",
        f"**Role type:** {jd.role_type}",
        f"**Industry:** {jd.industry}",
        f"**Seniority:** {jd.seniority}",
        f"**Required skills:** {', '.join(jd.required_skills)}",
        f"**Preferred skills:** {', '.join(jd.preferred_skills)}",
        f"**Keywords:** {', '.join(jd.keywords)}",
    ]
    if jd.key_responsibilities:
        lines.append("\n**Key responsibilities:**")
        for r in jd.key_responsibilities:
            lines.append(f"- {r}")
    return "\n".join(lines)


def tailor_resume(
    client: LLMClient,
    bank: ExperienceBank,
    jd: ParsedJD,
    settings: Settings,
    enriched_context: "EnrichedContext | None" = None,
) -> TailoredResume:
    """Run the tailoring agent — returns a TailoredResume."""
    bank_yaml = _bank_to_yaml_snippet(bank, jd, exclude_roles=settings.exclude_roles)
    jd_summary = _format_jd_summary(jd)

    user_prompt = build_tailor_user_prompt(
        jd_summary=jd_summary,
        bank_yaml=bank_yaml,
        max_exp_bullets=settings.max_bullets_per_experience,
        max_proj_bullets=settings.max_bullets_per_project,
        max_projects=settings.max_projects,
        enriched_context=enriched_context,
        emphasize_roles=settings.emphasize_roles,
        exclude_roles=settings.exclude_roles,
    )

    return client.complete(
        system=TAILOR_SYSTEM_PROMPT,
        user=user_prompt,
        response_model=TailoredResume,
    )
