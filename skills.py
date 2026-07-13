"""
SQLite-backed auto-learning skill library for Eling.
Upserts skills learned from exchanges and retrieves relevant ones.
"""

import sqlite3
import threading
from datetime import datetime, timezone
from typing import NamedTuple

from textsim import top_k


class Skill(NamedTuple):
    id: int
    name: str
    trigger: str
    body: str
    uses: int
    successes: int
    created_at: str
    updated_at: str


class SkillLibrary:
    """Auto-learning skill library backed by SQLite."""

    def __init__(self, db_path: str):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_table()

    def _create_table(self):
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS skills (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT    NOT NULL UNIQUE,
                    trigger     TEXT    NOT NULL,
                    body        TEXT    NOT NULL,
                    uses        INTEGER NOT NULL DEFAULT 0,
                    successes   INTEGER NOT NULL DEFAULT 0,
                    created_at  TEXT    NOT NULL,
                    updated_at  TEXT    NOT NULL
                )
            """)
            self._conn.commit()

    def upsert(self, name: str, trigger: str, body: str) -> Skill:
        """Insert a new skill or update an existing one by name."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            existing = self._conn.execute(
                "SELECT id FROM skills WHERE name = ?", (name,)
            ).fetchone()
            if existing:
                self._conn.execute(
                    "UPDATE skills SET trigger=?, body=?, updated_at=? WHERE name=?",
                    (trigger, body, now, name),
                )
            else:
                self._conn.execute(
                    "INSERT INTO skills (name, trigger, body, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (name, trigger, body, now, now),
                )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id, name, trigger, body, uses, successes, created_at, updated_at "
                "FROM skills WHERE name = ?",
                (name,),
            ).fetchone()
        return Skill(**dict(row))

    def get_by_name(self, name: str) -> Skill | None:
        """Fetch a single skill by its unique name."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, name, trigger, body, uses, successes, created_at, updated_at "
                "FROM skills WHERE name = ?",
                (name,),
            ).fetchone()
        return Skill(**dict(row)) if row else None

    def relevant(self, query: str, k: int = 3) -> list[tuple[Skill, float]]:
        """Return top-k (Skill, score) via text similarity on name+trigger."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, trigger, body, uses, successes, created_at, updated_at "
                "FROM skills"
            ).fetchall()
        all_skills = [Skill(**dict(r)) for r in rows]
        if not all_skills:
            return []

        def text_fn(s: Skill) -> str:
            return f"{s.name} {s.trigger}"

        return top_k(query, all_skills, text_fn, k=k, min_score=0.08)

    def record_use(self, name: str, success: bool):
        """Increment uses (and successes if successful) for a skill."""
        with self._lock:
            if success:
                self._conn.execute(
                    "UPDATE skills SET uses = uses + 1, successes = successes + 1 "
                    "WHERE name = ?",
                    (name,),
                )
            else:
                self._conn.execute(
                    "UPDATE skills SET uses = uses + 1 WHERE name = ?", (name,)
                )
            self._conn.commit()

    def forget(self, name: str) -> bool:
        """Delete a skill by name. Returns True if deleted."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM skills WHERE name = ?", (name,))
            self._conn.commit()
            return cur.rowcount > 0

    def count(self) -> int:
        """Return total number of skills (efficient COUNT)."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM skills").fetchone()
        return row[0] if row else 0
    
    def close(self):
        self._conn.close()
