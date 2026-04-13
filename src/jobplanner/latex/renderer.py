"""Render a TailoredResume into a LaTeX .tex file using Jinja2."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import jinja2

from jobplanner.bank.schema import ExperienceBank, TailoredResume


# LaTeX special characters that need escaping in dynamic text
_LATEX_SPECIAL = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
# Pre-compile for performance
_LATEX_ESCAPE_RE = re.compile("|".join(re.escape(k) for k in _LATEX_SPECIAL))


def _escape_latex(text: str) -> str:
    """Escape LaTeX special characters in user-provided text.

    Preserves backslash commands that are already LaTeX (like \\textbf).
    Only escapes the 9 standard special chars.
    """
    return _LATEX_ESCAPE_RE.sub(lambda m: _LATEX_SPECIAL[m.group()], text)


_COURSE_PREFIXES = re.compile(
    r"^(intro(duction)?\s+to|advanced|intermediate|topics\s+in|foundations\s+of|"
    r"principles\s+of|elements\s+of)\s+",
    re.IGNORECASE,
)


def _normalize_course(name: str) -> str:
    """Strip common prefixes/suffixes to extract the core course concept."""
    return _COURSE_PREFIXES.sub("", name.strip()).strip().lower()


def _dedup_coursework(
    coursework_map: dict[str, list[str]],
    per_school_cap: int = 4,
    total_cap: int = 8,
) -> dict[str, list[str]]:
    """Remove cross-school topic overlaps and enforce caps."""
    seen: set[str] = set()
    result: dict[str, list[str]] = {}
    total = 0
    for institution, courses in coursework_map.items():
        deduped: list[str] = []
        for c in courses:
            if len(deduped) >= per_school_cap or total >= total_cap:
                break
            key = _normalize_course(c)
            if key not in seen:
                seen.add(key)
                deduped.append(c)
                total += 1
        result[institution] = deduped
    return result


# ---------------------------------------------------------------------------
# Orphan-prevention: trim single-line paragraphs to fit
# ---------------------------------------------------------------------------
#
# The skills lines and Relevant Coursework line are single paragraphs
# rendered at \small. At our template width (7.3in text, 0.6in margins)
# a \small line fits approximately 115-120 visible characters before it
# wraps. LLM output regularly produces 130+ character lines (8 skills
# instead of 7, or 4 long course names instead of 3), which wrap with a
# 1-2 word orphan tail on line 2 and waste page space.
#
# These helpers drop items from the end of the list until the rendered
# paragraph is guaranteed to fit on one printed line. This is the
# structural fix for the orphan-wrap problem — the LaTeX preamble
# (emergencystretch + ragged2e) only absorbs a few characters of overflow,
# and cannot handle the 20-30 character overflows we see here.

# Safety budget, measured against the live template. A 130-char skills
# line renders with "architecture" orphaned on line 2 — so one-line
# capacity is ~117 chars. We target 115 to leave 2 chars of headroom.
_SKILLS_MAX_CHARS = 115
_COURSEWORK_MAX_CHARS = 120


def _trim_items_to_width(
    prefix: str,
    items: list[str],
    max_chars: int,
    separator: str = ", ",
) -> list[str]:
    """Drop items from the END of the list until ``prefix + join(items)`` fits.

    Operates on visible text (pre-LaTeX-escape) so the character count
    matches what the reader sees. Returns a (possibly shorter) copy of
    ``items``; does not mutate the input.
    """
    trimmed = list(items)
    while trimmed:
        rendered = prefix + separator.join(trimmed)
        if len(rendered) <= max_chars:
            return trimmed
        trimmed.pop()
    return trimmed


# ---------------------------------------------------------------------------
# Section ordering by candidate level (Stage 2)
# ---------------------------------------------------------------------------

_SECTION_ORDER_BY_LEVEL: dict[str, list[str]] = {
    "new_grad":    ["education", "skills", "experience", "projects"],
    "entry_level": ["experience", "skills", "education", "projects"],
    "mid_level":   ["skills", "experience", "projects", "education"],
    "senior_ic":   ["skills", "experience", "projects", "education"],
}


def _section_order_for_level(candidate_level: str) -> list[str]:
    """Return the ordered section list for a candidate level.

    Falls back to the new_grad order for unknown levels.
    """
    return _SECTION_ORDER_BY_LEVEL.get(
        candidate_level, _SECTION_ORDER_BY_LEVEL["new_grad"]
    )


@dataclass
class SpacingPreset:
    """Tunable spacing parameters for the 1-page retry loop."""
    section_space_before: str = "0.55em"
    section_space_after: str = "0.45em"
    item_topsep: str = "0.15em"
    item_itemsep: str = "0.1em"


# Progressively tighter presets for the retry loop
SPACING_PRESETS = [
    SpacingPreset(),  # default — matches Feb12.tex
    SpacingPreset(section_space_before="0.45em", section_space_after="0.35em",
                  item_topsep="0.1em", item_itemsep="0.05em"),
    SpacingPreset(section_space_before="0.35em", section_space_after="0.25em",
                  item_topsep="0.05em", item_itemsep="0.02em"),
    SpacingPreset(section_space_before="0.25em", section_space_after="0.15em",
                  item_topsep="0.02em", item_itemsep="0em"),
]


@dataclass
class RenderableExperience:
    organization: str
    role: str
    location: str
    dates: str
    bullets: list[str] = field(default_factory=list)


@dataclass
class RenderableProject:
    name: str
    dates: str
    url: str = ""
    subtitle: str = ""
    bullets: list[str] = field(default_factory=list)


def build_template_context(
    tailored: TailoredResume,
    bank: ExperienceBank,
    spacing: SpacingPreset | None = None,
) -> dict:
    """Build the Jinja2 context dict from a TailoredResume + bank."""
    if spacing is None:
        spacing = SPACING_PRESETS[0]

    # Build experience list
    experiences: list[RenderableExperience] = []
    for sel in tailored.selected_experiences:
        entry = bank.get_experience(sel.source_id)
        if entry is None:
            continue
        re_ = RenderableExperience(
            organization=_escape_latex(entry.organization),
            role=_escape_latex(entry.role),
            location=_escape_latex(entry.location),
            dates=entry.dates,
            bullets=[_escape_latex(b.text) for b in sel.bullets],
        )
        experiences.append(re_)

    # Build projects list
    projects: list[RenderableProject] = []
    for sel in tailored.selected_projects:
        entry = bank.get_project(sel.source_id)
        if entry is None:
            continue
        rp = RenderableProject(
            name=_escape_latex(entry.name),
            dates=entry.dates,
            url=entry.url,
            bullets=[_escape_latex(b.text) for b in sel.bullets],
        )
        projects.append(rp)

    # Build a map of selected coursework by institution with concept-level dedup
    coursework_map: dict[str, list[str]] = {}
    for sc in tailored.selected_coursework:
        coursework_map[sc.institution] = sc.courses
    coursework_map = _dedup_coursework(coursework_map)

    # Education
    education = []
    for edu in bank.education:
        courses = coursework_map.get(edu.institution, edu.coursework[:4])
        # Trim coursework to fit one printed line at \small
        courses = _trim_items_to_width(
            "Relevant Coursework: ", courses, _COURSEWORK_MAX_CHARS
        )
        education.append({
            "institution": _escape_latex(edu.institution),
            "degree": _escape_latex(edu.degree),
            "dates": edu.dates,
            "gpa": edu.gpa,
            "coursework": [_escape_latex(c) for c in courses],
            "honors": [_escape_latex(h) for h in edu.honors],
        })

    # Trim skills lines so each fits on one printed line at \small
    line1_label = tailored.skills.line1_label
    line1_items = _trim_items_to_width(
        f"{line1_label}: ", tailored.skills.line1, _SKILLS_MAX_CHARS
    )
    line2_label = tailored.skills.line2_label
    line2_items = _trim_items_to_width(
        f"{line2_label}: ", tailored.skills.line2, _SKILLS_MAX_CHARS
    )
    line3_label = tailored.skills.line3_label
    line3_items = _trim_items_to_width(
        f"{line3_label}: ", tailored.skills.line3, _SKILLS_MAX_CHARS
    )

    return {
        "meta": {
            "name": _escape_latex(bank.meta.name),
            "email": bank.meta.email,
            "phone": bank.meta.phone,
            "linkedin": bank.meta.linkedin,
            "github": bank.meta.github,
            "location": _escape_latex(bank.meta.location),
        },
        "education": education,
        "skills": {
            "line1_label": _escape_latex(line1_label),
            "line1": [_escape_latex(s) for s in line1_items],
            "line2_label": _escape_latex(line2_label),
            "line2": [_escape_latex(s) for s in line2_items],
            "line3_label": _escape_latex(line3_label),
            "line3": [_escape_latex(s) for s in line3_items],
        },
        "experiences": [
            {
                "organization": e.organization,
                "role": e.role,
                "location": e.location,
                "dates": e.dates,
                "bullets": e.bullets,
            }
            for e in experiences
        ],
        "projects": [
            {
                "name": p.name,
                "dates": p.dates,
                "url": p.url,
                "subtitle": p.subtitle,
                "bullets": p.bullets,
            }
            for p in projects
        ],
        "section_order": _section_order_for_level(bank.meta.candidate_level),
        "section_space_before": spacing.section_space_before,
        "section_space_after": spacing.section_space_after,
        "item_topsep": spacing.item_topsep,
        "item_itemsep": spacing.item_itemsep,
    }


def render_latex(
    tailored: TailoredResume,
    bank: ExperienceBank,
    template_dir: Path,
    template_name: str = "resume.tex.j2",
    spacing: SpacingPreset | None = None,
) -> str:
    """Render the tailored resume to a LaTeX string."""
    env = jinja2.Environment(
        block_start_string="<%",
        block_end_string="%>",
        variable_start_string="<<",
        variable_end_string=">>",
        comment_start_string="<#",
        comment_end_string="#>",
        loader=jinja2.FileSystemLoader(str(template_dir)),
        autoescape=False,
        keep_trailing_newline=True,
    )
    template = env.get_template(template_name)
    context = build_template_context(tailored, bank, spacing)
    return template.render(**context)
