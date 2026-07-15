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

# Recency weight in relevance scoring
# 0.0 = pure text similarity, 1.0 = pure recency
RECENCY_ALPHA = 0.20
# Half-life in days - recency score halves every N days
RECENCY_HALF_DAYS = 7.0


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
        self._db_path = db_path
        self._conn = self._connect_or_recover(db_path)
        self._create_table()

    def _connect_or_recover(self, db_path: str) -> sqlite3.Connection:
        """Connect to the database, recovering from corruption if needed."""
        # Clean stale WAL/SHM files first
        for ext in ("-wal", "-shm"):
            orphan = db_path + ext
            if os.path.exists(orphan):
                try:
                    os.remove(orphan)
                except OSError:
                    pass
        try:
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            return conn
        except sqlite3.DatabaseError:
            # Database corrupted — back it up and start fresh
            import shutil
            backup = db_path + ".corrupted"
            try:
                shutil.move(db_path, backup)
                print(f"⚠ Corrupted database moved to {backup}, creating fresh one.")
            except OSError:
                # Can't move? Try deleting directly
                try:
                    os.remove(db_path)
                except OSError:
                    pass
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            return conn

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

    def prune_old(self, keep: int = 500) -> int:
        """Delete all but the most recent `keep` entries. Returns count deleted."""
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) AS cnt FROM memory").fetchone()["cnt"]
            if total <= keep:
                return 0
            cutoff_id = self._conn.execute(
                "SELECT id FROM memory ORDER BY id DESC LIMIT 1 OFFSET ?",
                (keep - 1,),
            ).fetchone()
            if cutoff_id is None:
                return 0
            cur = self._conn.execute(
                "DELETE FROM memory WHERE id <= ?", (cutoff_id["id"],)
            )
            self._conn.commit()
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return cur.rowcount

    def prune_duplicates(self, threshold: float = 0.92) -> int:
        """Merge near-duplicate memory entries using text similarity.

        When two entries have text similarity above `threshold`, the older
        one is deleted. Returns count deleted.
        """
        all_entries = self.all()
        if len(all_entries) < 2:
            return 0

        def text_fn(e: MemoryEntry) -> str:
            return f"{e.user_input} {e.agent_output}"

        deleted = 0
        with self._lock:
            for i, entry in enumerate(all_entries):
                # Compare against newer entries only (avoids double-deletion)
                peers = all_entries[i + 1:]
                if not peers:
                    break
                dups = top_k(
                    text_fn(entry),
                    peers,
                    text_fn,
                    k=1,
                    min_score=threshold,
                )
                if dups:
                    dup_entry, _score = dups[0]
                    # Delete the older one
                    older_id = min(entry.id, dup_entry.id)
                    self._conn.execute("DELETE FROM memory WHERE id = ?", (older_id,))
                    deleted += 1
            if deleted:
                self._conn.commit()
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return deleted

    def all(self) -> list[MemoryEntry]:
        """Return every memory entry."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, timestamp, user_input, agent_output, outcome "
                "FROM memory ORDER BY id"
            ).fetchall()
        return [MemoryEntry(**dict(r)) for r in rows]

    def relevant(self, query: str, k: int = 5) -> list[tuple[MemoryEntry, float]]:
        """Return top-k (MemoryEntry, score) via text similarity + recency blend."""
        all_entries = self.all()
        if not all_entries:
            return []

        def text_fn(e: MemoryEntry) -> str:
            return f"{e.user_input} {e.agent_output}"

        results = top_k(query, all_entries, text_fn, k=len(all_entries), min_score=0.0)
        if not results:
            return []

        # Blend recency into scores
        now = datetime.now(timezone.utc)
        half_life_seconds = RECENCY_HALF_DAYS * 86400
        blended = []
        for entry, text_score in results:
            try:
                age = (now - datetime.fromisoformat(entry.timestamp)).total_seconds()
            except (ValueError, TypeError):
                age = 0.0
            recency_score = 2.0 ** (-age / half_life_seconds) if age >= 0 else 1.0
            blended_score = text_score * (1.0 - RECENCY_ALPHA) + recency_score * RECENCY_ALPHA
            blended.append((entry, blended_score))

        blended.sort(key=lambda x: x[1], reverse=True)
        return blended[:k]

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
