"""End-to-end pipeline orchestrator — ties all stages together."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import click

log = logging.getLogger(__name__)

from jobplanner.bank.loader import load_bank
from jobplanner.bank.schema import ExperienceBank, ParsedJD, TailoredResume
from jobplanner.checker.ats import ATSReport, check_ats
from jobplanner.checker.proofreader import ProofreadResult, proofread
from jobplanner.checker.critic import CriticResult, run_critic
from jobplanner.config import Settings
from jobplanner.latex.compiler import (
    compile_latex,
    detect_orphan_lines,
    get_page_count,
    get_page_fill_ratio,
)
from jobplanner.latex.renderer import SPACING_PRESETS, render_latex
from jobplanner.llm import create_client
from jobplanner.llm.base import LLMClient
from jobplanner.parser.jd_parser import parse_jd
from jobplanner.tailor.agent import tailor_resume
from jobplanner.tailor.enrichment import build_enriched_context
from jobplanner.tailor.length_gate import enforce_line_fill
from jobplanner.tailor.validator import ValidationResult, validate_tailored_resume


@dataclass
class PipelineResult:
    """Everything produced by a pipeline run."""

    jd: ParsedJD | None = None
    tailored: TailoredResume | None = None
    validation: ValidationResult | None = None
    critic_result: CriticResult | None = None
    tex_path: Path | None = None
    pdf_path: Path | None = None
    ats_report: ATSReport | None = None
    proofread_result: ProofreadResult | None = None
    output_dir: Path | None = None
    orphan_warnings: list[str] = field(default_factory=list)
    length_warnings: list[str] = field(default_factory=list)


def _trim_content(tailored: TailoredResume) -> str:
    """Progressively trim content to fit 1 page. Returns description of what was trimmed, or ''."""
    # 1. Drop a project if more than 2
    if len(tailored.selected_projects) > 2:
        dropped = tailored.selected_projects.pop()
        return f"dropped project {dropped.source_id}"

    # 2. Drop a bullet from the experience with the most bullets
    exps_with_extra = [s for s in tailored.selected_experiences if len(s.bullets) > 2]
    if exps_with_extra:
        longest = max(exps_with_extra, key=lambda s: len(s.bullets))
        longest.bullets.pop()
        return f"trimmed a bullet from {longest.source_id}"

    # 3. Drop a second project if still 2
    if len(tailored.selected_projects) > 1:
        dropped = tailored.selected_projects.pop()
        return f"dropped project {dropped.source_id}"

    # 4. Drop another bullet from any experience with more than 1
    exps_with_extra = [s for s in tailored.selected_experiences if len(s.bullets) > 1]
    if exps_with_extra:
        longest = max(exps_with_extra, key=lambda s: len(s.bullets))
        longest.bullets.pop()
        return f"trimmed a bullet from {longest.source_id}"

    # 5. Trim coursework
    if tailored.selected_coursework:
        for sc in tailored.selected_coursework:
            if len(sc.courses) > 3:
                sc.courses = sc.courses[:3]
                return f"trimmed coursework for {sc.institution}"

    return ""


def _sanitize(text: str, max_len: int = 30) -> str:
    """Lowercase, replace spaces/special chars with underscores, truncate."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:max_len]


def _make_output_dir(settings: Settings, jd: ParsedJD) -> Path:
    """Create a date-first nested output directory: output/YYYY-MM-DD/{company}_{title}/."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    company = _sanitize(jd.company) or "unknown"
    title = _sanitize(jd.title, 30) or (jd.role_type or "role")
    base_name = f"{company}_{title}"
    date_dir = settings.output_dir / date_str
    out = date_dir / base_name
    counter = 2
    while out.exists() and any(out.glob("*.pdf")):
        out = date_dir / f"{base_name}_{counter}"
        counter += 1
    out.mkdir(parents=True, exist_ok=True)
    return out


def _resume_filename(bank: ExperienceBank, jd: ParsedJD) -> str:
    """Build a descriptive resume filename stem, e.g. 'william_zhang_apple_swe'."""
    name = _sanitize(bank.meta.name, 40) or "resume"
    company = _sanitize(jd.company, 20) or "company"
    title = _sanitize(jd.title, 20) or (jd.role_type or "role")
    return f"{name}_{company}_{title}"


def run_pipeline(
    jd_text: str,
    settings: Settings,
    skip_proofread: bool = False,
    skip_critic: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> PipelineResult:
    """Execute the full tailoring pipeline.

    Stages:
    1. Parse JD
    2. Enrich context (load guidelines + market data)
    3. Tailor resume
    4. Validate (anti-hallucination)
    5. Critic/Improve (optional, skip with skip_critic=True)
    6. Re-validate after critic
    7. Render LaTeX
    8. Compile PDF (with 1-page retry loop)
    9. ATS check + optional proofread
    """

    def _emit(msg: str) -> None:
        click.echo(msg)
        if on_progress:
            on_progress(msg)

    result = PipelineResult()
    client = create_client(settings)
    bank = load_bank(settings.bank_path)

    # --- Stage 1: Parse JD ---
    _emit("Stage 1/9: Parsing job description...")
    result.jd = parse_jd(client, jd_text)
    _emit(f"  -> {result.jd.title} at {result.jd.company} ({result.jd.role_type})")

    # --- Stage 2: Enrich context ---
    _emit("Stage 2/9: Building enriched context...")
    tracker_db = settings.tracker_db_path
    enriched = build_enriched_context(
        role_type=result.jd.role_type,
        bank=bank,
        tracker_db=tracker_db if tracker_db.exists() else None,
        parsed_jd=result.jd,
    )
    boost_count = len(enriched.market_boost_skills)
    _emit(f"  -> Guidelines loaded, {boost_count} market-boost skills")

    # --- Stage 3: Tailor resume ---
    _emit("Stage 3/9: Tailoring resume...")
    result.tailored = tailor_resume(client, bank, result.jd, settings, enriched_context=enriched)
    n_exp = len(result.tailored.selected_experiences)
    n_proj = len(result.tailored.selected_projects)
    _emit(f"  -> Selected {n_exp} experiences, {n_proj} projects")

    # --- Stage 4: Validate ---
    _emit("Stage 4/9: Validating (anti-hallucination checks)...")
    result.validation = validate_tailored_resume(result.tailored, bank)
    if result.validation.warnings:
        for w in result.validation.warnings:
            icon = "X" if w.severity == "error" else "!"
            _emit(f"  [{icon}] {w.source_id}[{w.bullet_index}]: {w.message}")
    if not result.validation.passed:
        _emit("  VALIDATION FAILED — halting pipeline. Review warnings above.")
        return result
    _emit("  -> Passed")

    # --- Stage 5: Critic/Improve (optional) ---
    if not skip_critic:
        _emit("Stage 5/9: Critic pass (improving bullet quality)...")
        try:
            critic_result = run_critic(client, result.tailored, bank, result.jd, enriched)
            result.critic_result = critic_result
            _emit(f"  -> {critic_result.summary or 'Complete'}")
            if critic_result.bank_suggestions:
                high = sum(1 for s in critic_result.bank_suggestions if s.priority == "high")
                _emit(f"  -> {len(critic_result.bank_suggestions)} bank suggestions ({high} high priority)")
            # Re-validate the improved resume
            re_validation = validate_tailored_resume(critic_result.improved_resume, bank)
            if re_validation.passed:
                result.tailored = critic_result.improved_resume
                result.validation = re_validation
                _emit("  -> Re-validation passed — using improved resume")
            else:
                _emit("  -> Re-validation failed — keeping pre-critic resume")
        except Exception as exc:
            _emit(f"  -> Critic error ({exc}) — continuing without improvement")
    else:
        _emit("Stage 5/9: Critic pass skipped")

    # --- Length gate: programmatic enforcement of the 106-184 forbidden zone ---
    # This is the canonical orphan defense. LLMs cannot count characters; we
    # measure in Python and send one batched rewrite call only if any bullets
    # land in the forbidden zone. Zero API cost on clean runs.
    _emit("  Length gate: checking line-fill compliance...")
    _, length_warnings = enforce_line_fill(result.tailored, bank, client)
    result.length_warnings = length_warnings
    if length_warnings:
        _emit(f"  [!] {len(length_warnings)} bullet(s) could not be fixed to a safe length band:")
        for w in length_warnings:
            _emit(f"      - {w}")
    else:
        _emit("  -> All bullets in safe length bands.")

    # --- Stage 6: Persist bank suggestions ---
    bank_suggestions = result.critic_result.bank_suggestions if result.critic_result else []
    if bank_suggestions:
        try:
            from jobplanner.bank.suggestions import (
                init_tables, merge_suggestions, check_bank_staleness,
                mark_stale, update_bank_hash, check_for_conflicts,
            )
            conflicts = check_for_conflicts(tracker_db)
            if conflicts:
                _emit(f"  [!] Google Drive conflict copies detected next to {tracker_db.name}:")
                for cp in conflicts:
                    _emit(f"      - {cp.name}")
                _emit("      Resolve manually: pick the version to keep, rename it to "
                      f"{tracker_db.name}, delete the rest.")
                log.warning("Google Drive conflict copies detected near %s: %s",
                            tracker_db, [str(p) for p in conflicts])
            init_tables(tracker_db)
            if check_bank_staleness(tracker_db, settings.bank_path):
                stale_count = mark_stale(tracker_db)
                update_bank_hash(tracker_db, settings.bank_path)
                if stale_count:
                    _emit(f"  -> Bank changed — marked {stale_count} suggestion(s) as stale")
            jd_label = f"{result.jd.company} - {result.jd.title}"
            new_count = merge_suggestions(tracker_db, bank_suggestions, jd_label)
            _emit(f"  -> {new_count} new bank suggestion(s) persisted")
        except Exception as exc:
            _emit(f"  -> Suggestion persistence skipped: {exc}")

    # --- Stage 7+8: Render LaTeX + Compile PDF ---
    # The pipeline is ALWAYS strict one-page. No user-facing page-target toggle.
    out_dir = _make_output_dir(settings, result.jd)
    result.output_dir = out_dir
    file_stem = _resume_filename(bank, result.jd)
    min_fill_ratio = 0.93  # page must be at least 93% full (tight enough to eat bottom whitespace)

    pdf_path = None
    underfull_attempts = 0
    max_underfull_retries = 3
    max_attempts = settings.max_retries_for_one_page

    for attempt in range(max_attempts):
        # Use progressively tighter spacing, clamped to available presets
        spacing_idx = min(attempt, len(SPACING_PRESETS) - 1)
        spacing = SPACING_PRESETS[spacing_idx]

        _emit(f"Stage 7/9: Rendering LaTeX (attempt {attempt + 1})...")
        tex_content = render_latex(
            result.tailored, bank, settings.template_dir, spacing=spacing,
        )
        tex_path = out_dir / f"{file_stem}.tex"
        tex_path.write_text(tex_content, encoding="utf-8")
        result.tex_path = tex_path

        _emit("Stage 8/9: Compiling PDF...")
        try:
            pdf_path = compile_latex(tex_path, settings.latex_compiler)
        except RuntimeError as exc:
            _emit(f"  Compilation error: {exc}")
            return result

        pages = get_page_count(pdf_path)
        if pages > 1:
            # Once we've exhausted spacing presets, trim content progressively
            if spacing_idx >= len(SPACING_PRESETS) - 1 and result.tailored:
                trimmed = _trim_content(result.tailored)
                if trimmed:
                    _emit(f"  -> {pages} pages — {trimmed}")
                    continue
            _emit(f"  -> {pages} pages — too long, retrying with tighter spacing...")
            continue

        fill = get_page_fill_ratio(pdf_path)
        _emit(f"  -> {pdf_path.name} ({pages} page, {fill:.0%} full)")
        result.pdf_path = pdf_path

        if fill < min_fill_ratio and underfull_attempts < max_underfull_retries:
            underfull_attempts += 1
            if underfull_attempts == 1:
                settings.max_bullets_per_project = 3
                _emit(f"  -> Page {fill:.0%} full (need {min_fill_ratio:.0%}). "
                      "Retry 1: bumping project bullets to 3...")
            elif underfull_attempts == 2:
                settings.max_bullets_per_experience = 4
                _emit(f"  -> Page {fill:.0%} full (need {min_fill_ratio:.0%}). "
                      "Retry 2: bumping experience bullets to 4...")
            else:
                settings.max_projects = 3
                _emit(f"  -> Page {fill:.0%} full (need {min_fill_ratio:.0%}). "
                      "Retry 3: allowing a 3rd project...")
            result.tailored = tailor_resume(client, bank, result.jd, settings, enriched_context=enriched)
            n_exp = len(result.tailored.selected_experiences)
            n_proj = len(result.tailored.selected_projects)
            _emit(f"  -> Re-tailored: {n_exp} experiences, {n_proj} projects")
            result.validation = validate_tailored_resume(result.tailored, bank)
            if not result.validation.passed:
                _emit("  Re-validation failed — using previous version.")
                break
            # Re-enforce line-fill after re-tailor (the new bullets are fresh).
            _, retail_warnings = enforce_line_fill(result.tailored, bank, client)
            result.length_warnings = retail_warnings
            continue
        break
    else:
        if pdf_path:
            _emit("  Could not fit resume to 1 page after all retries.")
            result.pdf_path = pdf_path

    # --- Orphan-line verification ---
    # Post-render safety net: the LaTeX preamble defense (ragged2e +
    # \emergencystretch) should eliminate orphans, but we verify by scanning
    # the rendered PDF and emitting warnings for anything that slipped through.
    if result.pdf_path and result.pdf_path.exists():
        try:
            orphans = detect_orphan_lines(result.pdf_path)
        except Exception as exc:
            _emit(f"  Orphan detection skipped: {exc}")
            orphans = []
        if orphans:
            _emit(f"  [!] {len(orphans)} orphan wrap(s) detected:")
            for o in orphans:
                _emit(f"      - {o}")
            result.orphan_warnings = orphans
        else:
            _emit("  -> No orphan wraps detected.")

    # --- Stage 9: ATS check + proofread ---
    if result.pdf_path and result.pdf_path.exists():
        _emit("Stage 9/9: ATS check...")
        result.ats_report = check_ats(result.pdf_path, result.jd)
        _emit(f"  -> ATS score: {result.ats_report.score}/100")
        if result.ats_report.keyword_misses:
            _emit(f"  -> Missing keywords: {', '.join(result.ats_report.keyword_misses[:10])}")
        if result.ats_report.warnings:
            for w in result.ats_report.warnings:
                _emit(f"  [!] {w}")

        if not skip_proofread:
            _emit("  Proofreading...")
            result.proofread_result = proofread(client, result.ats_report.extracted_text)
            if result.proofread_result.clean:
                _emit("  -> Clean")
            else:
                for issue in result.proofread_result.issues:
                    _emit(f"  - {issue}")

        # Detect inferred skills used in the tailored resume
        inferred_names = {s.name.lower(): s for s in bank.inferred_skills}
        inferred_used: list[dict] = []
        if result.tailored:
            skills_in_resume: set[str] = set()
            for s in (result.tailored.skills.line1 + result.tailored.skills.line2
                      + result.tailored.skills.line3):
                skills_in_resume.add(s.lower())
            for name_lower, inf in inferred_names.items():
                if name_lower in skills_in_resume:
                    inferred_used.append({
                        "name": inf.name,
                        "basis": inf.basis,
                        "confidence": inf.confidence,
                    })

        # Write report
        report = {
            "company": result.jd.company,
            "title": result.jd.title,
            "role_type": result.jd.role_type,
            "ats_score": result.ats_report.score,
            "keyword_hits": result.ats_report.keyword_hits,
            "keyword_misses": result.ats_report.keyword_misses,
            "warnings": result.ats_report.warnings,
            "sections_found": result.ats_report.sections_found,
            "validation_passed": result.validation.passed if result.validation else None,
            "validation_warnings": [
                {"severity": w.severity, "source_id": w.source_id,
                 "bullet_index": w.bullet_index, "message": w.message}
                for w in (result.validation.warnings if result.validation else [])
            ],
            "inferred_skills_used": inferred_used,
            "bank_improvement_suggestions": [
                {
                    "source_id": s.source_id,
                    "bullet_index": s.bullet_index,
                    "issue": s.issue,
                    "suggestion": s.suggestion,
                    "priority": s.priority,
                }
                for s in (result.critic_result.bank_suggestions if result.critic_result else [])
            ],
            "enrichment_tokens": len(enriched.guidelines_excerpt + enriched.exemplary_bullets
                                     + enriched.structure_template) // 4,
            "market_boosted_skills": enriched.market_boost_skills,
            "critic_summary": result.critic_result.summary if result.critic_result else None,
            "orphan_warnings": result.orphan_warnings,
            "length_warnings": result.length_warnings,
        }
        report_path = out_dir / "report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        # Accumulate market data (silent sub-step after report write)
        try:
            from jobplanner.market.tracker import accumulate_jd
            accumulate_jd(tracker_db, result.jd)
            _emit("  -> Market data recorded")
        except Exception as exc:
            _emit(f"  -> Market accumulation skipped: {exc}")

        _emit(f"\nOutput: {out_dir}")

    return result
