"""SQLite-backed JD skill tracker.

Schema:
  jd_entries(id, company, title, role_type, seniority, industry, date_processed)
  jd_skills(id, jd_id, skill_name, skill_type)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from jobplanner.bank.schema import ExperienceBank, ParsedJD

_CREATE_ENTRIES = """
CREATE TABLE IF NOT EXISTS jd_entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company       TEXT NOT NULL,
    title         TEXT NOT NULL,
    role_type     TEXT NOT NULL,
    seniority     TEXT,
    industry      TEXT,
    date_processed TEXT NOT NULL
);
"""

_CREATE_SKILLS = """
CREATE TABLE IF NOT EXISTS jd_skills (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    jd_id      INTEGER NOT NULL REFERENCES jd_entries(id),
    skill_name TEXT NOT NULL,
    skill_type TEXT NOT NULL
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_skills_name ON jd_skills(skill_name);",
    "CREATE INDEX IF NOT EXISTS idx_skills_jd ON jd_skills(jd_id);",
    "CREATE INDEX IF NOT EXISTS idx_entries_role ON jd_entries(role_type);",
]

# Minimum JDs in a sector before market-boost kicks in
_MIN_JDS_FOR_BOOST = 10
# Fraction of JDs a skill must appear in to qualify for boosting
_BOOST_THRESHOLD = 0.5


def init_db(db_path: Path) -> None:
    """Create tables and indexes if they don't exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as con:
        con.execute(_CREATE_ENTRIES)
        con.execute(_CREATE_SKILLS)
        for idx in _CREATE_INDEXES:
            con.execute(idx)
        con.commit()


def accumulate_jd(db_path: Path, jd: ParsedJD) -> None:
    """Insert parsed JD skills into the tracker. Deduplicates by company+title+role_type."""
    if not db_path.exists():
        init_db(db_path)
    with sqlite3.connect(db_path) as con:
        # Deduplication check
        existing = con.execute(
            "SELECT id FROM jd_entries WHERE company=? AND title=? AND role_type=?",
            (jd.company, jd.title, jd.role_type),
        ).fetchone()
        if existing:
            return

        cur = con.execute(
            "INSERT INTO jd_entries (company, title, role_type, seniority, industry, date_processed) "
            "VALUES (?,?,?,?,?,?)",
            (jd.company, jd.title, jd.role_type, jd.seniority, jd.industry,
             datetime.now().date().isoformat()),
        )
        jd_id = cur.lastrowid

        rows = (
            [(jd_id, s, "required") for s in jd.required_skills]
            + [(jd_id, s, "preferred") for s in jd.preferred_skills]
            + [(jd_id, s, "keyword") for s in jd.keywords]
        )
        con.executemany(
            "INSERT INTO jd_skills (jd_id, skill_name, skill_type) VALUES (?,?,?)", rows
        )
        con.commit()


def get_sector_skill_counts(db_path: Path, role_type: str) -> dict[str, int]:
    """Return {skill_name: count} for all skills seen in JDs of this role_type."""
    if not db_path.exists():
        return {}
    with sqlite3.connect(db_path) as con:
        rows = con.execute(
            """
            SELECT s.skill_name, COUNT(DISTINCT e.id) as cnt
            FROM jd_skills s
            JOIN jd_entries e ON s.jd_id = e.id
            WHERE e.role_type = ?
            GROUP BY s.skill_name
            ORDER BY cnt DESC
            """,
            (role_type,),
        ).fetchall()
    return {row[0]: row[1] for row in rows}


def get_jd_count(db_path: Path, role_type: str) -> int:
    """Return the number of JDs processed for a given role type."""
    if not db_path.exists():
        return 0
    with sqlite3.connect(db_path) as con:
        return con.execute(
            "SELECT COUNT(*) FROM jd_entries WHERE role_type=?", (role_type,)
        ).fetchone()[0]


def get_skill_gaps(
    db_path: Path,
    role_type: str,
    bank: ExperienceBank,
    threshold: float = 0.3,
) -> list[dict]:
    """Return skills appearing in >=threshold of JDs that are NOT in the bank.

    Returns list of dicts: {skill, count, pct, in_bank}.
    """
    jd_count = get_jd_count(db_path, role_type)
    if jd_count == 0:
        return []
    counts = get_sector_skill_counts(db_path, role_type)
    bank_skills = bank.all_skill_names()
    gaps = []
    for skill, count in counts.items():
        pct = count / jd_count
        in_bank = skill.lower() in bank_skills
        gaps.append({"skill": skill, "count": count, "pct": pct, "in_bank": in_bank})
    return sorted(gaps, key=lambda x: x["pct"], reverse=True)


def get_market_boost_skills(
    db_path: Path,
    role_type: str,
    bank: ExperienceBank,
    parsed_jd: ParsedJD,
    threshold: float = _BOOST_THRESHOLD,
    min_jds: int = _MIN_JDS_FOR_BOOST,
) -> list[str]:
    """Skills appearing in >=threshold of sector JDs that the candidate HAS but this JD didn't ask for."""
    jd_count = get_jd_count(db_path, role_type)
    if jd_count < min_jds:
        return []
    counts = get_sector_skill_counts(db_path, role_type)
    bank_skills = bank.all_skill_names()
    jd_skills = {s.lower() for s in parsed_jd.required_skills + parsed_jd.preferred_skills}
    boost = []
    for skill, count in counts.items():
        pct = count / jd_count
        if pct >= threshold and skill.lower() in bank_skills and skill.lower() not in jd_skills:
            boost.append(skill)
    return boost


def get_cross_sector_skills(db_path: Path, role_types: list[str]) -> list[dict]:
    """Return skills with their frequency across multiple sectors."""
    if not db_path.exists():
        return []
    result: dict[str, dict] = {}
    counts_by_sector: dict[str, dict[str, int]] = {}
    jd_counts: dict[str, int] = {}
    for rt in role_types:
        counts_by_sector[rt] = get_sector_skill_counts(db_path, rt)
        jd_counts[rt] = get_jd_count(db_path, rt)
        for skill, count in counts_by_sector[rt].items():
            if skill not in result:
                result[skill] = {"skill": skill, "sectors": {}}
            if jd_counts[rt] > 0:
                result[skill]["sectors"][rt] = count / jd_counts[rt]
    rows = []
    for skill, data in result.items():
        pcts = list(data["sectors"].values())
        overall = sum(pcts) / len(pcts) if pcts else 0
        rows.append({"skill": skill, "sectors": data["sectors"], "overall_pct": overall})
    return sorted(rows, key=lambda x: x["overall_pct"], reverse=True)
