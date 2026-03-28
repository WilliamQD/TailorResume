"""Enriched context loader — assembles guidelines, examples, and market data per role type."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from jobplanner.bank.schema import ExperienceBank, ParsedJD

_GUIDELINES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "guidelines"


@dataclass
class EnrichedContext:
    """Assembled context injected into the tailor prompt."""
    guidelines_excerpt: str = ""       # Universal rules + matching sector rules
    exemplary_bullets: str = ""        # Few-shot good/bad bullets for this sector
    structure_template: str = ""       # Story arc + strategy for this sector
    market_boost_skills: list[str] = field(default_factory=list)


def _load_guidelines_excerpt(role_type: str) -> str:
    """Load universal sections + the matching sector subsection from resume_rules.md."""
    path = _GUIDELINES_DIR / "resume_rules.md"
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8")

    # Sections to always include (universal)
    universal_headers = [
        "## Bullet Writing",
        "## 6-Second Scan Optimization",
        "## ATS & Human Reader",
        "## Common Mistakes",
    ]

    # Map role_type to the sector header in the doc
    sector_header_map = {
        "swe": "### Software Engineering",
        "ds": "### Data Science / Statistics",
        "biostats": "### Data Science / Statistics",
        "mle": "### ML Engineering",
        "de": "### Data Engineering",
        "finance": "### Finance / Analyst",
        "analyst": "### Finance / Analyst",
        "research": "### Data Science / Statistics",
    }

    # Split into sections by ## headers
    sections: dict[str, str] = {}
    current_key = "__preamble__"
    current_lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("## "):
            sections[current_key] = "\n".join(current_lines)
            current_key = line
            current_lines = [line]
        else:
            current_lines.append(line)
    sections[current_key] = "\n".join(current_lines)

    # Within "## Sector-Specific Rules", extract just the matching subsection
    sector_section = sections.get("## Sector-Specific Rules", "")
    sector_header = sector_header_map.get(role_type, "")
    sector_excerpt = ""
    if sector_header and sector_section:
        # Find the matching ### block
        pattern = re.compile(rf"({re.escape(sector_header)}.*?)(?=\n### |\Z)", re.DOTALL)
        m = pattern.search(sector_section)
        if m:
            sector_excerpt = "## Sector-Specific Rules (your role type)\n\n" + m.group(1).strip()

    # Assemble: universal sections + sector
    parts = []
    for header in universal_headers:
        if header in sections:
            parts.append(sections[header].strip())
    if sector_excerpt:
        parts.append(sector_excerpt)

    return "\n\n---\n\n".join(parts)


def _load_exemplary_bullets(role_type: str) -> str:
    """Load exemplary bullets for a role type as a formatted string."""
    path = _GUIDELINES_DIR / "exemplary_bullets.yaml"
    if not path.exists():
        return ""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    # Fallback mapping for role types not directly in the YAML
    fallback_map = {"biostats": "biostats", "research": "ds", "other": None}
    key = fallback_map.get(role_type, role_type)
    if key is None or key not in data:
        return ""

    sector = data[key]
    lines = [f"### Exemplary Resume Bullets ({role_type.upper()})\n"]
    lines.append("**Strong examples (study the principles, not the content):**")
    for b in sector.get("bullets", [])[:4]:
        lines.append(f'\n- "{b["text"]}"')
        lines.append(f'  WHY GOOD: {b["why_good"]}')

    lines.append("\n**Anti-patterns to avoid:**")
    for b in sector.get("anti_patterns", [])[:2]:
        lines.append(f'\n- "{b["text"]}"')
        lines.append(f'  WHY BAD: {b["why_bad"]}')

    return "\n".join(lines)


def _load_structure_template(role_type: str) -> str:
    """Load the structure template for a role type as a formatted string."""
    path = _GUIDELINES_DIR / "resume_structures.yaml"
    if not path.exists():
        return ""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    fallback_map = {"biostats": "biostats", "research": "research", "other": "swe"}
    key = fallback_map.get(role_type, role_type)
    if key not in data:
        key = "swe"  # final fallback
    template = data[key]

    lines = [f"### Resume Strategy for {role_type.upper()} Roles\n"]
    lines.append(f"**Story arc:** {template.get('story_arc', '').strip()}")
    lines.append(f"\n**Top-1/3 scan strategy:** {template.get('top_third_strategy', '').strip()}")
    lines.append(f"\n**Bullet ordering:** {template.get('bullet_ordering', '').strip()}")
    lines.append(f"\n**Space allocation:**")
    for section, guidance in template.get("space_allocation", {}).items():
        lines.append(f"  - {section}: {guidance}")
    lines.append(f"\n**Coursework:** {template.get('coursework_strategy', '').strip()}")
    lines.append(f"\n**Skills section labels:** {template.get('skills_label_guidance', '').strip()}")

    return "\n".join(lines)


def build_enriched_context(
    role_type: str,
    bank: ExperienceBank,
    tracker_db: Path | None,
    parsed_jd: ParsedJD,
) -> EnrichedContext:
    """Assemble all enrichment data for a given role type."""
    guidelines = _load_guidelines_excerpt(role_type)
    bullets = _load_exemplary_bullets(role_type)
    structure = _load_structure_template(role_type)
    boost: list[str] = []

    if tracker_db and tracker_db.exists():
        from jobplanner.market.tracker import get_market_boost_skills
        boost = get_market_boost_skills(tracker_db, role_type, bank, parsed_jd)

    return EnrichedContext(
        guidelines_excerpt=guidelines,
        exemplary_bullets=bullets,
        structure_template=structure,
        market_boost_skills=boost,
    )
