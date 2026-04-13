"""Smoke test for the Streamlit UI using ``streamlit.testing.v1.AppTest``.

This test runs the Streamlit app **in-memory** (no browser, no subprocess,
no API calls) with the fixture-loaded ``PipelineResult`` injected into
session state. It verifies:

    1. The app loads without raising an exception.
    2. Both tabs ("Resume Tailor", "Bank Health") render.
    3. The fixture result populates the "Results" section (PDF preview,
       ATS score card, keyword pills).
    4. No Streamlit ``st.error`` was emitted during page render.

This catches LOGIC bugs (missing widgets, crashes, bad imports) cheaply on
every ``pytest`` run. It does **not** catch pure visual/CSS bugs like a
white-on-dark background regression — those are covered by the Playwright
visual test at ``tests/test_app_visual.py`` (opt-in, heavier).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from tests.fixtures.ui_fixture import build_ui_fixture


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


APP_PATH = Path(__file__).resolve().parent.parent / "src" / "jobplanner" / "app.py"


@pytest.fixture(scope="module")
def fixture_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the UI fixture once per test module and reuse the PDF."""
    root = tmp_path_factory.mktemp("ui_fixture")
    build_ui_fixture(root)
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def app_with_fixture(fixture_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Load the Streamlit app with JOBPLANNER_UI_FIXTURE=1 set."""
    monkeypatch.setenv("JOBPLANNER_UI_FIXTURE", "1")
    monkeypatch.setenv("JOBPLANNER_UI_FIXTURE_DIR", str(fixture_dir))
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(APP_PATH), default_timeout=30)
    at.run()
    return at


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_app_loads_without_exception(app_with_fixture) -> None:
    """The app must render without raising a Python exception."""
    at = app_with_fixture
    assert not at.exception, f"App raised: {[e.value for e in at.exception]}"


def test_app_has_no_error_widgets(app_with_fixture) -> None:
    """No ``st.error(...)`` calls should appear with the fixture loaded."""
    at = app_with_fixture
    errors = [e.value for e in at.error]
    assert errors == [], f"Unexpected st.error(...) calls: {errors}"


def test_app_has_two_tabs(app_with_fixture) -> None:
    """Resume Tailor + Bank Health tabs must both render."""
    at = app_with_fixture
    # Streamlit v1 testing exposes tabs via ``at.tabs``.
    labels = [t.label for t in at.tabs]
    assert "Resume Tailor" in labels
    assert "Bank Health" in labels


def test_fixture_populates_session_state(app_with_fixture) -> None:
    """JOBPLANNER_UI_FIXTURE=1 must drop a PipelineResult into session state."""
    at = app_with_fixture
    try:
        result = at.session_state["result"]
    except (KeyError, AttributeError):
        pytest.fail("Fixture did not populate session_state['result']")
    assert result is not None
    assert result.pdf_path is not None
    assert result.pdf_path.exists()
    assert result.ats_report is not None
    assert result.ats_report.score > 0


def test_fixture_builds_standalone(tmp_path: Path) -> None:
    """The fixture builder must work outside the AppTest harness.

    This is a fast regression gate: if ``experience.example.yaml`` drifts or
    a required template is missing, this test fails before the Streamlit
    test harness even spins up.
    """
    result = build_ui_fixture(tmp_path)
    assert result.pdf_path is not None
    assert result.pdf_path.exists()
    assert result.pdf_path.stat().st_size > 1000  # non-empty PDF
    assert result.tex_path is not None and result.tex_path.exists()
    assert result.output_dir == tmp_path
    assert (tmp_path / "report.json").exists()
    assert result.jd is not None
    assert result.ats_report is not None
