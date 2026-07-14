"""
SQLite-backed episodic memory for Eling.
Stores every user ↔ agent exchange with an outcome label.
"""

import os
import sqlite3
import threading
import hashlib
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
                    outcome     TEXT    NOT NULL DEFAULT 'neutral',
                    content_hash TEXT   NOT NULL DEFAULT ''
                )
            """)
            # Add content_hash column if upgrading from older schema
            try:
                self._conn.execute("ALTER TABLE memory ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass  # column already exists
            # Index on content_hash for fast dedup lookups
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_hash ON memory(content_hash)")
            self._conn.commit()

    def _hash(self, user_input: str, agent_output: str) -> str:
        """SHA-256 of the normalized exchange content."""
        raw = f"{user_input.strip()}|{agent_output.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def add(self, user_input: str, agent_output: str, outcome: str = "neutral") -> int:
        """Store an exchange and return its row id. Skips duplicates."""
        ts = datetime.now(timezone.utc).isoformat()
        content_hash = self._hash(user_input, agent_output)
        with self._lock:
            # Dedup: skip if the same exchange already exists
            existing = self._conn.execute(
                "SELECT id FROM memory WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()
            if existing is not None:
                return existing["id"]

            cur = self._conn.execute(
                "INSERT INTO memory (timestamp, user_input, agent_output, outcome, content_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                (ts, user_input, agent_output, outcome, content_hash),
            )
            self._conn.commit()
            return cur.lastrowid

    def count(self) -> int:
        """Return the number of stored memory entries (without loading them)."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS cnt FROM memory").fetchone()
            return row["cnt"]

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
        """Close the database connection and clean up WAL files."""
        db_path = None
        with self._lock:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                db_path = self._conn.execute("PRAGMA database_list").fetchone()[2]
            except Exception:
                pass
        self._conn.close()
        # Remove orphan WAL/SHM files that SQLite leaves behind
        if db_path:
            for _ext in ("-wal", "-shm"):
                _orphan = db_path + _ext
                try:
                    if os.path.exists(_orphan):
                        os.remove(_orphan)
                except OSError:
                    pass
