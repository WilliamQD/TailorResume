"""Build a complete ``PipelineResult`` without calling any LLM API.

The Streamlit UI verification tests need a realistic resume + PDF so they
can exercise every results-panel code path (PDF preview, ATS score card,
keyword pills, orphan banner, suggestions). Running the real pipeline costs
API tokens and introduces flakiness, so this module synthesizes a
``PipelineResult`` from deterministic inputs:

    1. Load the gitted ``data/experience.example.yaml`` as the bank.
    2. Build a hand-authored ``TailoredResume`` whose selections all reference
       real ids in the example bank.
    3. Render it to .tex and compile to a real PDF via ``tectonic``.
    4. Run the real ATS check against the rendered PDF.
    5. Run the real orphan detector against the rendered PDF.
    6. Return a ``PipelineResult`` that looks like the real thing.

The fixture is consumed by:
    - ``tests/test_app_smoke.py`` — ``streamlit.testing.v1.AppTest`` run
    - ``tests/test_app_visual.py`` — Playwright visual snapshot test
    - The running Streamlit app when ``JOBPLANNER_UI_FIXTURE=1`` is set,
      which lets a developer eyeball the fixture UI state in a browser.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

from jobplanner.bank.loader import load_bank
from jobplanner.bank.schema import (
    ParsedJD,
    SelectedCoursework,
    SelectedExperience,
    SelectedProject,
    SkillsSection,
    TailoredBullet,
    TailoredResume,
)
from jobplanner.checker.ats import check_ats
from jobplanner.latex.compiler import compile_latex, detect_orphan_lines
from jobplanner.latex.renderer import render_latex
from jobplanner.pipeline import PipelineResult
from jobplanner.tailor.validator import validate_tailored_resume


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_EXAMPLE_BANK_PATH = _REPO_ROOT / "data" / "experience.example.yaml"
_TEMPLATES_DIR = _REPO_ROOT / "data" / "templates"


def _build_tailored_from_example_bank() -> TailoredResume:
    """Hand-authored TailoredResume whose ids line up with experience.example.yaml.

    Keep this aligned with the example bank: if the example bank's ids
    change, this factory must be updated or the fixture PDF will fail to
    render. A CI smoke test catches the drift — see
    ``tests/test_ui_fixture.py::test_fixture_builds``.
    """
    return TailoredResume(
        selected_experiences=[
            SelectedExperience(
                source_id="acme_analytics_swe",
                bullets=[
                    TailoredBullet(
                        source_bullet_indices=[0],
                        text=(
                            "Built a Python microservice that served 12k req/s "
                            "on 8 pods, using FastAPI, Redis, and Postgres "
                            "with full observability and graceful shutdown."
                        ),
                    ),
                    TailoredBullet(
                        source_bullet_indices=[1],
                        text=(
                            "Cut p99 latency from 850ms to 230ms by adding "
                            "read-through caching and pooled connections "
                            "across the order-intake path."
                        ),
                    ),
                ],
            ),
            SelectedExperience(
                source_id="healthtech_lab_intern",
                bullets=[
                    TailoredBullet(
                        source_bullet_indices=[0],
                        text=(
                            "Designed a pandas + scikit-learn experiment "
                            "harness that tracked 40 models across 6 folds "
                            "and published results to an internal dashboard."
                        ),
                    ),
                    TailoredBullet(
                        source_bullet_indices=[0],
                        text=(
                            "Published a short paper on the approach and "
                            "released the harness as an open-source repo "
                            "with reproducible environment setup."
                        ),
                    ),
                ],
            ),
        ],
        selected_projects=[
            SelectedProject(
                source_id="ml_pipeline",
                bullets=[
                    TailoredBullet(
                        source_bullet_indices=[0],
                        text=(
                            "Shipped a Next.js + FastAPI app that classifies "
                            "receipts with a fine-tuned ViT, backed by a "
                            "Postgres ledger and a background worker queue."
                        ),
                    ),
                    TailoredBullet(
                        source_bullet_indices=[0],
                        text=(
                            "Added auth, role-based access, and a metered "
                            "Stripe billing flow for trial and paid tiers "
                            "with usage tracking per API key."
                        ),
                    ),
                ],
            ),
        ],
        skills=SkillsSection(
            line1_label="Languages & Systems",
            line1=["Python", "TypeScript", "SQL", "Go", "Rust", "Bash"],
            line2_label="Frameworks & Tools",
            line2=["FastAPI", "Next.js", "Postgres", "Redis", "Docker", "Kubernetes"],
            line3_label="ML & Data",
            line3=["PyTorch", "scikit-learn", "pandas", "Airflow", "dbt", "MLflow"],
        ),
        selected_coursework=[
            SelectedCoursework(
                institution="University of California, Berkeley",
                courses=[
                    "Machine Learning",
                    "Natural Language Processing",
                    "Distributed Systems",
                    "Database Systems",
                ],
            ),
            SelectedCoursework(
                institution="University of Michigan",
                courses=[
                    "Data Structures & Algorithms",
                    "Operating Systems",
                    "Computer Architecture",
                    "Software Engineering",
                ],
            ),
        ],
    )


def _build_parsed_jd() -> ParsedJD:
    """A realistic ParsedJD for the fixture — drives the JD card + keyword pills."""
    return ParsedJD(
        title="Backend Engineer, Platform",
        company="Example Corp",
        role_type="swe",
        required_skills=["Python", "FastAPI", "Postgres", "Kubernetes", "Redis"],
        preferred_skills=["Go", "Rust", "dbt"],
        keywords=["distributed systems", "observability", "latency", "reliability"],
        key_responsibilities=[
            "Own the reliability of the order-intake path.",
            "Build backend services used by every downstream team.",
        ],
        qualifications=[
            "3+ years of backend experience.",
            "Strong Python and SQL fundamentals.",
        ],
        industry="software",
        seniority="mid",
        raw_text=(
            "We're hiring a backend engineer to own our order-intake "
            "platform. You'll work in Python + FastAPI, ship services "
            "to Kubernetes, and partner with the SRE team on latency "
            "and reliability goals."
        ),
    )


def build_ui_fixture(output_dir: Path) -> PipelineResult:
    """Build a fully-populated PipelineResult at ``output_dir``.

    This function does the same work as a real pipeline run (render, compile,
    validate, ATS, orphan check) but skips every LLM call. It's safe to run
    in CI — no API keys needed, no network calls, no token cost.

    Args:
        output_dir: Directory that will hold ``resume.tex``, ``resume.pdf``,
            and ``report.json``. Must exist and be writable.

    Returns:
        A ``PipelineResult`` that the Streamlit app can render without
        modification.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    bank = load_bank(_EXAMPLE_BANK_PATH)
    tailored = _build_tailored_from_example_bank()
    parsed_jd = _build_parsed_jd()

    validation = validate_tailored_resume(tailored, bank)

    # Render LaTeX using the real renderer + real templates.
    tex_source = render_latex(tailored, bank, template_dir=_TEMPLATES_DIR)
    tex_path = output_dir / "fixture_resume.tex"
    tex_path.write_text(tex_source, encoding="utf-8")

    # Compile with tectonic (real compile — matches the production path).
    pdf_path = compile_latex(tex_path)

    # Real ATS check against the compiled PDF.
    ats_report = check_ats(pdf_path, parsed_jd)

    # Real orphan detection.
    orphan_warnings = detect_orphan_lines(pdf_path)

    result = PipelineResult(
        jd=parsed_jd,
        tailored=tailored,
        validation=validation,
        critic_result=None,
        tex_path=tex_path,
        pdf_path=pdf_path,
        ats_report=ats_report,
        proofread_result=None,
        output_dir=output_dir,
        orphan_warnings=orphan_warnings,
    )

    # Mirror the real pipeline's report.json so the app's ``load_report``
    # helper returns something non-empty in the fixture path.
    report = {
        "jd": parsed_jd.model_dump(),
        "tailored": tailored.model_dump(),
        "ats": asdict(ats_report) if ats_report else None,
        "orphan_warnings": orphan_warnings,
        "inferred_skills_used": [],
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )

    return result


def clear_fixture_dir(path: Path) -> None:
    """Remove a fixture output directory if it exists — used between runs."""
    if path.exists():
        shutil.rmtree(path)
