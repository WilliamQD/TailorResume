"""Tests for jobplanner.latex.renderer helpers."""

from __future__ import annotations

from jobplanner.latex.renderer import _trim_items_to_width


def test_trim_no_op_when_fits():
    result = _trim_items_to_width("Label: ", ["A", "B", "C"], 30)
    assert result == ["A", "B", "C"]


def test_trim_drops_from_end():
    # "Label: AAAA, BBBB, CCCC, DDDD" = 30 chars — over 25
    # "Label: AAAA, BBBB, CCCC" = 24 chars — fits
    result = _trim_items_to_width("Label: ", ["AAAA", "BBBB", "CCCC", "DDDD"], 25)
    assert result == ["AAAA", "BBBB", "CCCC"]


def test_trim_empty_items():
    result = _trim_items_to_width("Very long prefix: ", [], 10)
    assert result == []


def test_trim_single_item_too_long():
    """Even a single item can't fit — returns empty."""
    result = _trim_items_to_width("Prefix: ", ["ThisIsWayTooLong"], 10)
    assert result == []


def test_trim_real_skills_line():
    """Reproduce the John Hancock failure: 8 skills at ~130 chars."""
    items = [
        "Python", "SQL", "ETL", "data-pipelines", "data-quality",
        "data-integration", "data-governance", "data architecture",
    ]
    prefix = "Data Engineering & Pipelines: "
    result = _trim_items_to_width(prefix, items, 115)
    rendered = prefix + ", ".join(result)
    assert len(rendered) <= 115
    assert len(result) < len(items)  # something was dropped


def test_trim_real_coursework_line():
    """Reproduce the John Hancock coursework failure."""
    courses = [
        "Clinical Databases & Ontologies",
        "Advanced Statistical Programming (SAS & R)",
        "Statistical Practice I & II",
        "Linear Models",
    ]
    prefix = "Relevant Coursework: "
    result = _trim_items_to_width(prefix, courses, 120)
    rendered = prefix + ", ".join(result)
    assert len(rendered) <= 120


def test_trim_does_not_mutate_input():
    original = ["A", "B", "C", "D"]
    copy = list(original)
    _trim_items_to_width("Prefix: ", original, 15)
    assert original == copy
