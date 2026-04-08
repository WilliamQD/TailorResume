"""Persistent bank suggestion storage backed by SQLite.

Suggestions are accumulated across JD runs and tracked for frequency,
recency, and staleness (when the experience bank is modified).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from jobplanner.checker.critic import BankSuggestion

_PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}

_CREATE_SUGGESTIONS = """\
CREATE TABLE IF NOT EXISTS bank_suggestions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id    TEXT    NOT NULL,
    bullet_index INTEGER NOT NULL,
    issue        TEXT    NOT NULL,
    suggestion   TEXT    NOT NULL,
    priority     TEXT    NOT NULL DEFAULT 'medium',
    first_seen   TEXT    NOT NULL,
    last_seen    TEXT    NOT NULL,
    seen_count   INTEGER NOT NULL DEFAULT 1,
    status       TEXT    NOT NULL DEFAULT 'active',
    source_jds   TEXT    NOT NULL DEFAULT '[]'
);
"""

_CREATE_META = """\
CREATE TABLE IF NOT EXISTS bank_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_bsug_source ON bank_suggestions(source_id);",
    "CREATE INDEX IF NOT EXISTS idx_bsug_status ON bank_suggestions(status);",
]


def init_tables(db_path: Path) -> None:
    """Create suggestion tables idempotently."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as con:
        con.execute(_CREATE_SUGGESTIONS)
        con.execute(_CREATE_META)
        for idx in _CREATE_INDEXES:
            con.execute(idx)
        con.commit()


def merge_suggestions(
    db_path: Path,
    suggestions: list[BankSuggestion],
    jd_label: str,
) -> int:
    """Upsert suggestions from a single JD run. Returns count of newly inserted rows."""
    now = datetime.now().isoformat(timespec="seconds")
    new_count = 0
    with sqlite3.connect(db_path) as con:
        for s in suggestions:
            row = con.execute(
                "SELECT id, seen_count, priority, source_jds, status "
                "FROM bank_suggestions "
                "WHERE source_id=? AND bullet_index=? AND issue=?",
                (s.source_id, s.bullet_index, s.issue),
            ).fetchone()
            if row:
                sid, count, old_pri, jds_json, status = row
                jds = json.loads(jds_json)
                if jd_label not in jds:
                    jds.append(jd_label)
                new_pri = s.priority if _PRIORITY_RANK.get(s.priority, 0) > _PRIORITY_RANK.get(old_pri, 0) else old_pri
                new_status = "active" if status == "stale" else status
                con.execute(
                    "UPDATE bank_suggestions SET seen_count=?, last_seen=?, "
                    "priority=?, source_jds=?, suggestion=?, status=? WHERE id=?",
                    (count + 1, now, new_pri, json.dumps(jds), s.suggestion, new_status, sid),
                )
            else:
                con.execute(
                    "INSERT INTO bank_suggestions "
                    "(source_id, bullet_index, issue, suggestion, priority, "
                    " first_seen, last_seen, seen_count, status, source_jds) "
                    "VALUES (?,?,?,?,?,?,?,1,'active',?)",
                    (s.source_id, s.bullet_index, s.issue, s.suggestion,
                     s.priority, now, now, json.dumps([jd_label])),
                )
                new_count += 1
        con.commit()
    return new_count


def get_all_suggestions(
    db_path: Path,
    status: str | None = None,
) -> list[dict]:
    """Query suggestions, optionally filtered by status. Sorted by seen_count desc, priority desc."""
    if not db_path.exists():
        return []
    init_tables(db_path)
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        if status:
            rows = con.execute(
                "SELECT * FROM bank_suggestions WHERE status=? "
                "ORDER BY seen_count DESC, "
                "CASE priority WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC, "
                "last_seen DESC",
                (status,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM bank_suggestions "
                "ORDER BY seen_count DESC, "
                "CASE priority WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC, "
                "last_seen DESC",
            ).fetchall()
    return [dict(r) for r in rows]


def get_suggestion_counts(db_path: Path) -> dict[str, int]:
    """Return counts by status: {'active': N, 'stale': N, 'dismissed': N}."""
    if not db_path.exists():
        return {"active": 0, "stale": 0, "dismissed": 0}
    init_tables(db_path)
    with sqlite3.connect(db_path) as con:
        rows = con.execute(
            "SELECT status, COUNT(*) FROM bank_suggestions GROUP BY status"
        ).fetchall()
    counts = {"active": 0, "stale": 0, "dismissed": 0}
    for status, cnt in rows:
        counts[status] = cnt
    return counts


def dismiss_suggestion(db_path: Path, suggestion_id: int) -> None:
    """Mark a suggestion as dismissed."""
    with sqlite3.connect(db_path) as con:
        con.execute(
            "UPDATE bank_suggestions SET status='dismissed' WHERE id=?",
            (suggestion_id,),
        )
        con.commit()


def dismiss_all_stale(db_path: Path) -> int:
    """Dismiss all stale suggestions. Returns count affected."""
    with sqlite3.connect(db_path) as con:
        cur = con.execute(
            "UPDATE bank_suggestions SET status='dismissed' WHERE status='stale'"
        )
        con.commit()
        return cur.rowcount


def _file_hash(path: Path) -> str:
    """SHA-256 hex digest of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_bank_staleness(db_path: Path, bank_path: Path) -> bool:
    """Return True if the bank file has changed since last stored hash."""
    current = _file_hash(bank_path)
    with sqlite3.connect(db_path) as con:
        row = con.execute(
            "SELECT value FROM bank_meta WHERE key='bank_hash'"
        ).fetchone()
    if not row:
        return True  # no hash stored yet — treat as changed
    return row[0] != current


def update_bank_hash(db_path: Path, bank_path: Path) -> None:
    """Store the current bank file hash."""
    current = _file_hash(bank_path)
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT OR REPLACE INTO bank_meta (key, value) VALUES ('bank_hash', ?)",
            (current,),
        )
        con.commit()


def mark_stale(db_path: Path) -> int:
    """Mark all active suggestions as stale. Returns count affected."""
    with sqlite3.connect(db_path) as con:
        cur = con.execute(
            "UPDATE bank_suggestions SET status='stale' WHERE status='active'"
        )
        con.commit()
        return cur.rowcount
