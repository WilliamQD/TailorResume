"""Click CLI entry point for JobPlanner."""

from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml

from jobplanner.config import MODEL_MAP, load_settings


@click.group()
@click.option("--model", default=None, help=f"LLM model ({', '.join(MODEL_MAP.keys())})")
@click.pass_context
def cli(ctx: click.Context, model: str | None) -> None:
    """JobPlanner — automated resume tailoring pipeline."""
    overrides = {}
    if model:
        overrides["model"] = model
    ctx.ensure_object(dict)
    ctx.obj["settings"] = load_settings(**overrides)


# -------------------------------------------------------------------------
# tailor — the main pipeline
# -------------------------------------------------------------------------

@cli.command()
@click.option("--jd", required=True, type=click.Path(exists=True), help="Path to job description text file")
@click.option("--skip-proofread", is_flag=True, help="Skip the LLM proofreading step")
@click.option("--skip-critic", is_flag=True, help="Skip the critic/improve pass")
@click.pass_context
def tailor(ctx: click.Context, jd: str, skip_proofread: bool, skip_critic: bool) -> None:
    """Run the full resume tailoring pipeline."""
    from jobplanner.pipeline import run_pipeline

    settings = ctx.obj["settings"]
    jd_text = Path(jd).read_text(encoding="utf-8")

    result = run_pipeline(jd_text, settings, skip_proofread=skip_proofread, skip_critic=skip_critic)

    if result.pdf_path and result.pdf_path.exists():
        click.echo(f"\nResume: {result.pdf_path}")
        click.echo(f"LaTeX:  {result.tex_path}")
        if result.output_dir:
            click.echo(f"Report: {result.output_dir / 'report.json'}")
    else:
        click.echo("\nPipeline did not produce a PDF. Check errors above.", err=True)
        sys.exit(1)


# -------------------------------------------------------------------------
# preview — dry run (no PDF generation)
# -------------------------------------------------------------------------

@cli.command()
@click.option("--jd", required=True, type=click.Path(exists=True), help="Path to JD file")
@click.pass_context
def preview(ctx: click.Context, jd: str) -> None:
    """Dry run: show what the AI would select without generating a PDF."""
    from jobplanner.bank.loader import load_bank
    from jobplanner.llm import create_client
    from jobplanner.parser.jd_parser import parse_jd
    from jobplanner.tailor.agent import tailor_resume

    settings = ctx.obj["settings"]
    client = create_client(settings)
    bank = load_bank(settings.bank_path)
    jd_text = Path(jd).read_text(encoding="utf-8")

    click.echo("Parsing JD...")
    parsed = parse_jd(client, jd_text)
    click.echo(f"  {parsed.title} at {parsed.company} ({parsed.role_type})")
    click.echo(f"  Required: {', '.join(parsed.required_skills[:10])}")

    click.echo("\nTailoring...")
    tailored = tailor_resume(client, bank, parsed, settings)

    click.echo("\n--- Selected Experiences ---")
    for sel in tailored.selected_experiences:
        exp = bank.get_experience(sel.source_id)
        name = exp.organization if exp else sel.source_id
        click.echo(f"\n  {name}:")
        for b in sel.bullets:
            click.echo(f"    [{','.join(str(i) for i in b.source_bullet_indices)}] {b.text[:120]}...")

    click.echo("\n--- Selected Projects ---")
    for sel in tailored.selected_projects:
        proj = bank.get_project(sel.source_id)
        name = proj.name if proj else sel.source_id
        click.echo(f"\n  {name}:")
        for b in sel.bullets:
            click.echo(f"    [{','.join(str(i) for i in b.source_bullet_indices)}] {b.text[:120]}...")

    click.echo("\n--- Skills ---")
    click.echo(f"  {tailored.skills.line1_label}: {', '.join(tailored.skills.line1)}")
    click.echo(f"  {tailored.skills.line2_label}: {', '.join(tailored.skills.line2)}")
    if tailored.skills.line3:
        click.echo(f"  {tailored.skills.line3_label}: {', '.join(tailored.skills.line3)}")


# -------------------------------------------------------------------------
# compile — just compile .tex to PDF
# -------------------------------------------------------------------------

@cli.command()
@click.argument("tex_file", type=click.Path(exists=True))
def compile(tex_file: str) -> None:
    """Compile a .tex file to PDF."""
    from jobplanner.latex.compiler import compile_latex, get_page_count

    pdf = compile_latex(Path(tex_file))
    pages = get_page_count(pdf)
    click.echo(f"Compiled: {pdf} ({pages} page{'s' if pages != 1 else ''})")


# -------------------------------------------------------------------------
# ats-check — run ATS check on existing PDF
# -------------------------------------------------------------------------

@cli.command("ats-check")
@click.argument("pdf_file", type=click.Path(exists=True))
def ats_check(pdf_file: str) -> None:
    """Run ATS compliance check on an existing PDF."""
    from jobplanner.checker.ats import check_ats

    report = check_ats(Path(pdf_file))
    click.echo(f"ATS Score: {report.score}/100")
    click.echo(f"Sections: {', '.join(report.sections_found)}")
    if report.warnings:
        click.echo("\nWarnings:")
        for w in report.warnings:
            click.echo(f"  [!] {w}")
    if not report.warnings:
        click.echo("No issues found.")


# -------------------------------------------------------------------------
# bank — subcommands for experience bank management
# -------------------------------------------------------------------------

@cli.group()
def bank() -> None:
    """Manage the experience bank."""
    pass


@bank.command("validate")
@click.pass_context
def bank_validate(ctx: click.Context) -> None:
    """Validate experience.yaml against the schema."""
    from jobplanner.bank.loader import validate_bank

    settings = ctx.obj["settings"]
    warnings = validate_bank(settings.bank_path)
    if warnings:
        click.echo("Validation warnings:")
        for w in warnings:
            click.echo(f"  [!] {w}")
        sys.exit(1)
    else:
        click.echo("experience.yaml is valid.")


@bank.command("show")
@click.pass_context
def bank_show(ctx: click.Context) -> None:
    """Show a summary of the experience bank."""
    from jobplanner.bank.loader import load_bank

    settings = ctx.obj["settings"]
    b = load_bank(settings.bank_path)

    click.echo(f"Name: {b.meta.name}")
    click.echo(f"\nEducation: {len(b.education)} entries")
    for edu in b.education:
        click.echo(f"  - {edu.institution}: {edu.degree}")

    click.echo(f"\nExperiences: {len(b.experience)} entries")
    for exp in b.experience:
        click.echo(f"  - [{exp.id}] {exp.organization} — {exp.role} ({len(exp.bullets)} bullets)")

    click.echo(f"\nProjects: {len(b.projects)} entries")
    for proj in b.projects:
        click.echo(f"  - [{proj.id}] {proj.name} ({len(proj.bullets)} bullets)")

    click.echo(f"\nSkills: {len(b.skills.languages)} languages, "
               f"{len(b.skills.frameworks)} frameworks, {len(b.skills.tools)} tools")
    total_bullets = sum(len(e.bullets) for e in b.experience) + sum(len(p.bullets) for p in b.projects)
    click.echo(f"Total bullets: {total_bullets}")


@bank.command("update")
@click.pass_context
def bank_update(ctx: click.Context) -> None:
    """AI-assisted bank update — describe changes in natural language."""
    from jobplanner.bank.updater import update_bank_interactive
    from jobplanner.llm import create_client

    settings = ctx.obj["settings"]
    client = create_client(settings)
    update_bank_interactive(client, settings.bank_path)


@bank.command("add")
@click.pass_context
def bank_add(ctx: click.Context) -> None:
    """Interactively scaffold a new experience or project entry."""
    from jobplanner.bank.updater import add_entry_interactive

    settings = ctx.obj["settings"]
    add_entry_interactive(settings.bank_path)


@bank.command("edit")
@click.pass_context
def bank_edit(ctx: click.Context) -> None:
    """Open experience.yaml in your default editor."""
    settings = ctx.obj["settings"]
    click.edit(filename=str(settings.bank_path))


# -------------------------------------------------------------------------
# market — subcommands for market intelligence
# -------------------------------------------------------------------------

@cli.group()
def market() -> None:
    """Market intelligence — skill demand analysis from processed JDs."""
    pass


@market.command("report")
@click.option("--sector", default=None, help="Role type to report on (swe, ds, mle, de, finance, analyst)")
@click.option("--cross-sector", "cross_sector", is_flag=True, help="Show cross-sector comparison")
@click.pass_context
def market_report(ctx: click.Context, sector: str | None, cross_sector: bool) -> None:
    """Show skill demand report and gap analysis from processed JDs."""
    from jobplanner.bank.loader import load_bank
    from jobplanner.market.report import format_cross_sector_report, format_sector_report
    from jobplanner.market.tracker import get_jd_count

    settings = ctx.obj["settings"]
    bank = load_bank(settings.bank_path)
    db_path = settings.output_dir.parent / "data" / "market" / "skill_tracker.db"

    if not db_path.exists():
        click.echo("No market data yet. Run 'jobplanner tailor' on some JDs to accumulate data.")
        return

    if cross_sector:
        click.echo(format_cross_sector_report(db_path, bank))
        return

    if sector:
        click.echo(format_sector_report(db_path, sector, bank))
    else:
        # Show summary of all sectors with data
        for rt in ["swe", "ds", "mle", "de", "finance", "analyst", "biostats"]:
            n = get_jd_count(db_path, rt)
            if n > 0:
                click.echo(f"\n{rt.upper()}: {n} JDs")
        click.echo("\nUse --sector <type> for detailed report, --cross-sector for comparison.")


@market.command("suggest-projects")
@click.option("--sector", required=True, help="Role type to suggest projects for")
@click.pass_context
def suggest_projects(ctx: click.Context, sector: str) -> None:
    """Suggest projects to fill skill gaps for a target sector."""
    from jobplanner.bank.loader import load_bank
    from jobplanner.llm import create_client
    from jobplanner.market.report import suggest_projects_prompt
    from jobplanner.market.tracker import get_skill_gaps

    settings = ctx.obj["settings"]
    bank = load_bank(settings.bank_path)
    client = create_client(settings)
    db_path = settings.output_dir.parent / "data" / "market" / "skill_tracker.db"

    if not db_path.exists():
        click.echo("No market data yet. Run the pipeline on some JDs first.")
        return

    gaps = get_skill_gaps(db_path, sector, bank)
    prompt = suggest_projects_prompt(sector, gaps, bank)

    if not prompt:
        click.echo(f"No significant skill gaps found for {sector.upper()}. Your bank looks comprehensive!")
        return

    click.echo(f"\nGenerating project suggestions for {sector.upper()} gaps...\n")
    response = client.complete_text(
        system="You are a career advisor. Be specific and practical.",
        user=prompt,
    )
    click.echo(response)
