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

    # Build a map of selected coursework by institution
    coursework_map: dict[str, list[str]] = {}
    for sc in tailored.selected_coursework:
        coursework_map[sc.institution] = sc.courses

    # Education
    education = []
    for edu in bank.education:
        # Use LLM-selected coursework if available, else fall back to bank (capped at 8)
        courses = coursework_map.get(edu.institution, edu.coursework[:6])
        education.append({
            "institution": _escape_latex(edu.institution),
            "degree": _escape_latex(edu.degree),
            "dates": edu.dates,
            "gpa": edu.gpa,
            "coursework": [_escape_latex(c) for c in courses],
            "honors": [_escape_latex(h) for h in edu.honors],
        })

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
            "line1_label": _escape_latex(tailored.skills.line1_label),
            "line1": [_escape_latex(s) for s in tailored.skills.line1],
            "line2_label": _escape_latex(tailored.skills.line2_label),
            "line2": [_escape_latex(s) for s in tailored.skills.line2],
            "line3_label": _escape_latex(tailored.skills.line3_label),
            "line3": [_escape_latex(s) for s in tailored.skills.line3],
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
