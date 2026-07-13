"""
SQLite-backed episodic memory for Eling.
Stores every user ↔ agent exchange with an outcome label.
"""

import sqlite3
import threading
from datetime import datetime, timezone
from typing import NamedTuple

from textsim import top_k


class MemoryEntry(NamedTuple):
    id: int
    timestamp: str
    user_input: str
    agent_output: str
    outcome: str


class MemoryStore:
    """Episodic memory backed by SQLite."""

    def __init__(self, db_path: str):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_table()

    def _create_table(self):
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS memory (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT    NOT NULL,
                    user_input  TEXT    NOT NULL,
                    agent_output TEXT   NOT NULL,
                    outcome     TEXT    NOT NULL DEFAULT 'neutral'
                )
            """)
            self._conn.commit()

    def add(self, user_input: str, agent_output: str, outcome: str = "neutral") -> int:
        """Store an exchange and return its row id."""
        ts = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO memory (timestamp, user_input, agent_output, outcome) "
                "VALUES (?, ?, ?, ?)",
                (ts, user_input, agent_output, outcome),
            )
            self._conn.commit()
            return cur.lastrowid

    def all(self) -> list[MemoryEntry]:
        """Return every memory entry."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, timestamp, user_input, agent_output, outcome "
                "FROM memory ORDER BY id"
            ).fetchall()
        return [MemoryEntry(**dict(r)) for r in rows]

    def relevant(self, query: str, k: int = 5) -> list[tuple[MemoryEntry, float]]:
        """Return top-k (MemoryEntry, score) via text similarity."""
        all_entries = self.all()
        if not all_entries:
            return []

        def text_fn(e: MemoryEntry) -> str:
            return f"{e.user_input} {e.agent_output}"

        results = top_k(query, all_entries, text_fn, k=k, min_score=0.05)
        return results  # list of (MemoryEntry, float)

    def recent(self, n: int = 5) -> list[MemoryEntry]:
        """Return the last n entries in chronological order."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, timestamp, user_input, agent_output, outcome "
                "FROM memory ORDER BY id DESC LIMIT ?",
                (n,),
            ).fetchall()
        # reverse to chronological order
        return [MemoryEntry(**dict(r)) for r in reversed(rows)]

    def close(self):
        self._conn.close()
