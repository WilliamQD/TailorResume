"""Tests for the SQLite skill tracker."""
from __future__ import annotations

import pytest
from jobplanner.market.tracker import (
    accumulate_jd,
    get_market_boost_skills,
    get_sector_skill_counts,
    init_db,
)


def test_init_db_creates_tables(tmp_db):
    init_db(tmp_db)
    import sqlite3
    con = sqlite3.connect(tmp_db)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "jd_entries" in tables
    assert "jd_skills" in tables
    con.close()


def test_accumulate_jd_inserts_entry(tmp_db, minimal_jd):
    init_db(tmp_db)
    accumulate_jd(tmp_db, minimal_jd)
    import sqlite3
    con = sqlite3.connect(tmp_db)
    count = con.execute("SELECT COUNT(*) FROM jd_entries").fetchone()[0]
    assert count == 1
    company = con.execute("SELECT company FROM jd_entries").fetchone()[0]
    assert company == minimal_jd.company
    con.close()


def test_accumulate_jd_inserts_skills(tmp_db, minimal_jd):
    init_db(tmp_db)
    accumulate_jd(tmp_db, minimal_jd)
    import sqlite3
    con = sqlite3.connect(tmp_db)
    skills = {r[0] for r in con.execute("SELECT skill_name FROM jd_skills").fetchall()}
    # required_skills from minimal_jd: ["Python", "FastAPI"]
    assert "Python" in skills
    assert "FastAPI" in skills
    con.close()


def test_accumulate_jd_deduplicates(tmp_db, minimal_jd):
    init_db(tmp_db)
    accumulate_jd(tmp_db, minimal_jd)
    accumulate_jd(tmp_db, minimal_jd)  # second insert — same JD
    import sqlite3
    con = sqlite3.connect(tmp_db)
    count = con.execute("SELECT COUNT(*) FROM jd_entries").fetchone()[0]
    assert count == 1  # not 2
    con.close()


def test_get_sector_skill_counts_empty(tmp_db):
    init_db(tmp_db)
    counts = get_sector_skill_counts(tmp_db, "swe")
    assert counts == {}


def test_get_sector_skill_counts(tmp_db, minimal_jd):
    init_db(tmp_db)
    accumulate_jd(tmp_db, minimal_jd)
    counts = get_sector_skill_counts(tmp_db, "swe")
    assert counts.get("Python", 0) >= 1


def test_get_market_boost_skills_empty_db(tmp_db, minimal_bank, minimal_jd):
    init_db(tmp_db)
    boost = get_market_boost_skills(tmp_db, "swe", minimal_bank, minimal_jd)
    assert boost == []


def test_get_market_boost_skills_below_threshold(tmp_db, minimal_bank, minimal_jd):
    """With fewer than 10 JDs, no boost skills returned."""
    init_db(tmp_db)
    for _ in range(5):  # 5 JDs < 10 threshold
        # Need slightly different keys to avoid dedup; but dedup is by company+title+role_type
        # So 5 identical JDs → only 1 inserted. Adjust test expectation:
        accumulate_jd(tmp_db, minimal_jd)
    boost = get_market_boost_skills(tmp_db, "swe", minimal_bank, minimal_jd)
    assert boost == []
