"""Tests for the enrichment context builder."""
from __future__ import annotations

from pathlib import Path
import pytest
from jobplanner.tailor.enrichment import EnrichedContext, build_enriched_context


GUIDELINES_DIR = Path("data/guidelines")


@pytest.mark.skipif(
    not (GUIDELINES_DIR / "resume_rules.md").exists(),
    reason="data/guidelines not yet created",
)
def test_enriched_context_loads_guidelines(minimal_bank, minimal_jd):
    ctx = build_enriched_context(
        role_type="swe",
        bank=minimal_bank,
        tracker_db=None,
        parsed_jd=minimal_jd,
    )
    assert isinstance(ctx, EnrichedContext)
    assert len(ctx.guidelines_excerpt) > 100
    assert "Bullet Writing" in ctx.guidelines_excerpt
    assert "Software Engineering" in ctx.guidelines_excerpt
    # Other sectors not injected
    assert "Data Science" not in ctx.guidelines_excerpt


def test_enriched_context_loads_exemplary_bullets(minimal_bank, minimal_jd):
    ctx = build_enriched_context(
        role_type="swe",
        bank=minimal_bank,
        tracker_db=None,
        parsed_jd=minimal_jd,
    )
    assert len(ctx.exemplary_bullets) > 50
    assert "why_good" in ctx.exemplary_bullets or "Leads with" in ctx.exemplary_bullets


def test_enriched_context_loads_structure(minimal_bank, minimal_jd):
    ctx = build_enriched_context(
        role_type="swe",
        bank=minimal_bank,
        tracker_db=None,
        parsed_jd=minimal_jd,
    )
    assert len(ctx.structure_template) > 20
    assert "swe" in ctx.structure_template.lower() or "scale" in ctx.structure_template.lower()


def test_enriched_context_no_market_boost_when_db_missing(minimal_bank, minimal_jd):
    ctx = build_enriched_context(
        role_type="swe",
        bank=minimal_bank,
        tracker_db=None,
        parsed_jd=minimal_jd,
    )
    assert ctx.market_boost_skills == []


def test_enriched_context_graceful_missing_sector(minimal_bank, minimal_jd):
    """Falls back gracefully if a sector has no exemplary bullets."""
    minimal_jd.role_type = "other"
    ctx = build_enriched_context(
        role_type="other",
        bank=minimal_bank,
        tracker_db=None,
        parsed_jd=minimal_jd,
    )
    assert isinstance(ctx, EnrichedContext)  # no crash
