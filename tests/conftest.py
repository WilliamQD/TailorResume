"""Shared test fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

from jobplanner.bank.schema import (
    Bullet, Education, Experience, ExperienceBank,
    InferredSkill, Meta, ParsedJD, Project, Skills,
)


@pytest.fixture
def minimal_bank() -> ExperienceBank:
    return ExperienceBank(
        meta=Meta(name="Test User", email="t@t.com"),
        education=[
            Education(
                institution="Test University",
                school="Engineering",
                degree="BS Computer Science",
                dates="2022-2024",
                coursework=["Algorithms", "Systems", "ML"],
            )
        ],
        experience=[
            Experience(
                id="exp_acme",
                organization="Acme Corp",
                role="Software Engineer",
                dates="2024-Present",
                tags=["swe", "backend"],
                bullets=[
                    Bullet(
                        description="Built an API gateway handling 10K req/s",
                        tech_stack=["Python", "FastAPI"],
                        skills=["backend", "swe"],
                        metrics="10K req/s, p99 < 20ms",
                    ),
                    Bullet(
                        description="Migrated PostgreSQL schema to support multi-tenancy",
                        tech_stack=["PostgreSQL"],
                        skills=["database"],
                        metrics="0 downtime migration",
                    ),
                ],
            )
        ],
        projects=[
            Project(
                id="proj_ml",
                name="ML Pipeline",
                dates="2024",
                tags=["ml", "python"],
                anchor=True,
                bullets=[
                    Bullet(
                        description="End-to-end training pipeline with MLflow tracking",
                        tech_stack=["Python", "MLflow", "PyTorch"],
                        skills=["mle"],
                        metrics="",
                    )
                ],
            )
        ],
        skills=Skills(
            languages=["Python", "SQL"],
            frameworks=["FastAPI", "PyTorch"],
            tools=["Docker", "Git"],
        ),
        inferred_skills=[
            InferredSkill(name="Bayesian Inference", basis="STA501 coursework", confidence="moderate"),
        ],
    )


@pytest.fixture
def minimal_jd() -> ParsedJD:
    return ParsedJD(
        title="Software Engineer",
        company="TestCo",
        role_type="swe",
        required_skills=["Python", "FastAPI"],
        preferred_skills=["Docker"],
        keywords=["backend", "API"],
        seniority="entry",
    )


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """A temporary SQLite DB path (file does not exist yet)."""
    return tmp_path / "skill_tracker.db"
