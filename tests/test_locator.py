"""Tests for jobplanner.bank.locator.find_bullet_line."""

from __future__ import annotations

from pathlib import Path

from jobplanner.bank.locator import find_bullet_line

EXAMPLE_BANK = Path(__file__).resolve().parent.parent / "data" / "experience.example.yaml"


def test_first_bullet() -> None:
    assert find_bullet_line(EXAMPLE_BANK, "acme_analytics_swe", 0) == 68


def test_second_bullet() -> None:
    assert find_bullet_line(EXAMPLE_BANK, "acme_analytics_swe", 1) == 78


def test_third_bullet() -> None:
    assert find_bullet_line(EXAMPLE_BANK, "acme_analytics_swe", 2) == 88


def test_out_of_range_falls_back_to_id_line() -> None:
    # acme_analytics_swe has 3 bullets; index 999 is out-of-range,
    # so we expect a fallback to the id line itself (line 61).
    assert find_bullet_line(EXAMPLE_BANK, "acme_analytics_swe", 999) == 61


def test_nonexistent_id_returns_none() -> None:
    assert find_bullet_line(EXAMPLE_BANK, "definitely_not_in_the_bank", 0) is None


def test_next_entry_isolated() -> None:
    # The walk must stop at the next sibling `- id:` so bullet 0 of the next
    # entry resolves to its own first description, not a bullet of the prior one.
    assert find_bullet_line(EXAMPLE_BANK, "healthtech_lab_intern", 0) == 105


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert find_bullet_line(tmp_path / "nonexistent.yaml", "anything", 0) is None
