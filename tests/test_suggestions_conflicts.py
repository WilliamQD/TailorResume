"""Tests for Google Drive conflict-copy detection in bank.suggestions."""

from __future__ import annotations

from pathlib import Path

from jobplanner.bank.suggestions import check_for_conflicts


def test_no_conflicts_returns_empty(tmp_path: Path) -> None:
    db = tmp_path / "skill_tracker.db"
    db.write_bytes(b"sqlite-stub")
    assert check_for_conflicts(db) == []


def test_missing_parent_returns_empty(tmp_path: Path) -> None:
    db = tmp_path / "does_not_exist" / "skill_tracker.db"
    assert check_for_conflicts(db) == []


def test_detects_numbered_conflict(tmp_path: Path) -> None:
    db = tmp_path / "skill_tracker.db"
    db.write_bytes(b"sqlite-stub")
    conflict = tmp_path / "skill_tracker (1).db"
    conflict.write_bytes(b"sqlite-stub")

    found = check_for_conflicts(db)
    assert found == [conflict]


def test_detects_named_conflict(tmp_path: Path) -> None:
    db = tmp_path / "skill_tracker.db"
    db.write_bytes(b"sqlite-stub")
    conflict = tmp_path / "skill_tracker - Conflict copy from Williams-MBP.db"
    conflict.write_bytes(b"sqlite-stub")

    found = check_for_conflicts(db)
    assert found == [conflict]


def test_detects_multiple_conflicts_sorted(tmp_path: Path) -> None:
    db = tmp_path / "skill_tracker.db"
    db.write_bytes(b"sqlite-stub")
    a = tmp_path / "skill_tracker (1).db"
    b = tmp_path / "skill_tracker (2).db"
    a.write_bytes(b"a")
    b.write_bytes(b"b")

    found = check_for_conflicts(db)
    assert found == [a, b]


def test_ignores_unrelated_db_files(tmp_path: Path) -> None:
    db = tmp_path / "skill_tracker.db"
    db.write_bytes(b"sqlite-stub")
    (tmp_path / "other_database.db").write_bytes(b"x")
    (tmp_path / "experience.yaml").write_text("name: test")

    assert check_for_conflicts(db) == []
