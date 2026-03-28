"""Market intelligence report generation — CLI output for gap analysis."""

from __future__ import annotations

from pathlib import Path

from jobplanner.bank.schema import ExperienceBank
from jobplanner.market.tracker import (
    get_cross_sector_skills,
    get_jd_count,
    get_skill_gaps,
)


def format_sector_report(
    db_path: Path,
    role_type: str,
    bank: ExperienceBank,
    top_n: int = 20,
) -> str:
    """Format a per-sector skill demand report as a string."""
    jd_count = get_jd_count(db_path, role_type)
    if jd_count == 0:
        return f"No JDs recorded for sector '{role_type}' yet. Run the pipeline on some JDs first."

    gaps = get_skill_gaps(db_path, role_type, bank, threshold=0.0)[:top_n]

    lines = [
        f"\n{role_type.upper()} Market Report ({jd_count} JD{'s' if jd_count != 1 else ''} analyzed)",
        "-" * 50,
        f"{'Skill':<28} {'Freq':>6}  {'You Have':>8}  {'Gap':>4}",
        "-" * 50,
    ]
    missing = []
    for item in gaps:
        skill = item["skill"]
        pct = item["pct"]
        have = "yes" if item["in_bank"] else "no"
        gap = "<-- MISSING" if not item["in_bank"] and pct >= 0.3 else ""
        lines.append(f"  {skill:<26} {pct:>5.0%}  {have:>8}  {gap}")
        if not item["in_bank"] and pct >= 0.3:
            missing.append((skill, pct))

    if missing:
        lines.append("\nGap Suggestions:")
        for skill, pct in missing[:5]:
            lines.append(f"  - Add {skill} ({pct:.0%} of {role_type.upper()} JDs require it)")

    return "\n".join(lines)


def format_cross_sector_report(
    db_path: Path,
    bank: ExperienceBank,
    role_types: list[str] | None = None,
    top_n: int = 20,
) -> str:
    """Format a cross-sector skill demand comparison."""
    if role_types is None:
        role_types = ["swe", "ds", "mle", "de", "finance", "analyst"]

    active = [rt for rt in role_types if get_jd_count(db_path, rt) > 0]
    if not active:
        return "No JDs recorded yet. Run the pipeline on JDs for multiple sectors first."

    skills = get_cross_sector_skills(db_path, active)[:top_n]
    bank_skills = bank.all_skill_names()

    counts_header = "  ".join(f"{rt.upper():>6}" for rt in active)
    lines = [
        "\nCross-Sector Skill Demand",
        "-" * 70,
        f"{'Skill':<28}  {counts_header}  {'Overall':>8}  Status",
        "-" * 70,
    ]
    high_leverage = []
    for item in skills:
        skill = item["skill"]
        sector_pcts = "  ".join(
            f"{item['sectors'].get(rt, 0):>6.0%}" for rt in active
        )
        overall = item["overall_pct"]
        have = "yes" if skill.lower() in bank_skills else "MISSING"
        lines.append(f"  {skill:<26}  {sector_pcts}  {overall:>7.0%}  {have}")
        if skill.lower() not in bank_skills and overall >= 0.4 and len(item["sectors"]) >= 2:
            high_leverage.append((skill, overall, len(item["sectors"])))

    if high_leverage:
        lines.append("\nHigh-Leverage Gaps (appear in multiple sectors):")
        for skill, pct, n_sectors in sorted(high_leverage, key=lambda x: -x[1])[:5]:
            lines.append(f"  - {skill} -- {pct:.0%} overall, found in {n_sectors} sectors")

    return "\n".join(lines)


def suggest_projects_prompt(
    role_type: str,
    gaps: list[dict],
    bank: ExperienceBank,
) -> str:
    """Build a prompt for LLM project suggestion based on skill gaps."""
    missing = [(g["skill"], g["pct"]) for g in gaps if not g["in_bank"] and g["pct"] >= 0.3][:8]
    if not missing:
        return ""

    existing_projects = [p.name for p in bank.projects]
    skill_list = "\n".join(f"  - {s} ({pct:.0%} of JDs)" for s, pct in missing)
    project_list = "\n".join(f"  - {p}" for p in existing_projects)

    return f"""You are a career advisor helping a new grad build projects to fill skill gaps.

Target role: {role_type.upper()}

Missing skills (appear in many JDs but candidate lacks):
{skill_list}

Existing projects (do NOT suggest duplicates):
{project_list}

Suggest 2-3 concrete project ideas that:
1. Fill the most important skill gaps above
2. Are achievable in 1-4 weeks
3. Are distinct from existing projects
4. Would be impressive to a {role_type.upper()} hiring manager

For each project, include:
- Project name and brief description (2 sentences)
- Skills demonstrated (map to the gaps above)
- Suggested tech stack
- Key deliverable that proves the skill

Be specific. No generic CRUD apps or "build a todo list" suggestions."""
