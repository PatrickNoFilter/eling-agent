"""
SQLite-backed auto-learning skill library for Eling.
Implements: success-rate boosted ranking, dedup on insert,
semantic embedding fallback, body versioning, and low-performer pruning.
"""

import logging
import sqlite3
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from textsim import top_k

log = logging.getLogger("eling.skills")

# ── Optional: sentence-transformers for semantic retrieval ─────────
_SENTENCE_TRANSFORMERS_AVAILABLE = False
_sentence_model = None

try:
    import sentence_transformers
    _SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    pass


def _get_sentence_model():
    global _sentence_model
    if _SENTENCE_TRANSFORMERS_AVAILABLE and _sentence_model is None:
        try:
            _sentence_model = sentence_transformers.SentenceTransformer(
                "all-MiniLM-L6-v2"
            )
            log.info("SentenceTransformer model loaded for semantic skill retrieval")
        except Exception as exc:
            log.debug("SentenceTransformer load failed: %s", exc)
    return _sentence_model


def _cosine_sim_vec(a, b) -> float:
    """Cosine similarity between two embedding vectors (numpy arrays)."""
    import numpy as np
    dot = float(np.dot(a, b))
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# ── Constants ──────────────────────────────────────────────────────
SUCCESS_ALPHA = 0.30        # weight of success-rate in blended score
DEDUP_THRESHOLD = 0.85      # cosine-sim threshold for dedup
LOW_PERFORMER_MIN_USES = 5  # min uses before considering low-performer prune
LOW_PERFORMER_MAX_RATE = 0.30  # max success-rate to qualify as low-performer
BODY_MAX_LENGTH = 2000      # max chars for skill body


class Skill(NamedTuple):
    id: int
    name: str
    trigger: str
    body: str
    uses: int
    successes: int
    prior_body: str | None
    prior_trigger: str | None
    created_at: str
    updated_at: str


class SkillLibrary:
    """Auto-learning skill library backed by SQLite with quality improvements."""

    def __init__(self, db_path: str):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_table()
        self._migrate()
        # Ring buffer for min_score diagnostic logging
        self._query_log: deque[tuple[str, float, int]] = deque(maxlen=50)

    def _create_table(self):
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS skills (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    name          TEXT    NOT NULL UNIQUE,
                    trigger       TEXT    NOT NULL,
                    body          TEXT    NOT NULL,
                    uses          INTEGER NOT NULL DEFAULT 0,
                    successes     INTEGER NOT NULL DEFAULT 0,
                    prior_body    TEXT,
                    prior_trigger TEXT,
                    created_at    TEXT    NOT NULL,
                    updated_at    TEXT    NOT NULL
                )
            """)
            self._conn.commit()

    def _migrate(self):
        """Add columns that may not exist in older databases."""
        additions = [
            ("prior_body",    "TEXT"),
            ("prior_trigger", "TEXT"),
        ]
        for col, coltype in additions:
            try:
                with self._lock:
                    self._conn.execute(
                        f"ALTER TABLE skills ADD COLUMN {col} {coltype}"
                    )
                    self._conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists

    # ── Helpers ────────────────────────────────────────────────────

    def _row_to_skill(self, row) -> Skill:
        return Skill(
            id=row["id"],
            name=row["name"],
            trigger=row["trigger"],
            body=row["body"],
            uses=row["uses"],
            successes=row["successes"],
            prior_body=self._safe_col(row, "prior_body"),
            prior_trigger=self._safe_col(row, "prior_trigger"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _safe_col(row, col: str):
        """Safely get a column that might not exist in old rows."""
        try:
            return row[col]
        except (KeyError, IndexError):
            return None

    def _fetch_all(self) -> list[Skill]:
        rows = self._conn.execute(
            "SELECT id, name, trigger, body, uses, successes, "
            "prior_body, prior_trigger, created_at, updated_at "
            "FROM skills"
        ).fetchall()
        return [self._row_to_skill(r) for r in rows]

    def _fetch_by_name(self, name: str) -> Skill | None:
        row = self._conn.execute(
            "SELECT id, name, trigger, body, uses, successes, "
            "prior_body, prior_trigger, created_at, updated_at "
            "FROM skills WHERE name = ?",
            (name,),
        ).fetchone()
        return self._row_to_skill(row) if row else None

    # ── Blended relevance score ────────────────────────────────────

    @staticmethod
    def _bayesian_success_rate(uses: int, successes: int) -> float:
        """Bayesian-smoothed success rate: (successes+1)/(uses+2)."""
        return (successes + 1) / (uses + 2)

    def _blend_score(self, text_score: float, uses: int, successes: int) -> float:
        """Blend text similarity with Bayesian success rate."""
        rate = self._bayesian_success_rate(uses, successes)
        return text_score * (1.0 - SUCCESS_ALPHA) + rate * SUCCESS_ALPHA

    # ── Core operations ────────────────────────────────────────────

    def upsert(self, name: str, trigger: str, body: str) -> Skill:
        """Insert a new skill or update an existing one by name.

        Features:
        - Truncates body to BODY_MAX_LENGTH
        - Stores previous body/trigger before overwriting (versioning)
        - Dedup check: skips if a very similar skill already exists
        """
        # Quality: cap body length
        body = body[:BODY_MAX_LENGTH]

        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            existing = self._conn.execute(
                "SELECT id FROM skills WHERE name = ?", (name,)
            ).fetchone()

            # ── Dedup check (skip if similar skill exists under a diff name) ──
            if not existing:
                all_skills = self._fetch_all()
                if all_skills:

                    def text_fn(s: Skill) -> str:
                        return f"{s.name} {s.trigger} {s.body[:500]}"

                    dups = top_k(
                        f"{name} {trigger} {body[:500]}",
                        all_skills,
                        text_fn,
                        k=1,
                        min_score=DEDUP_THRESHOLD,
                    )
                    if dups:
                        dup_skill, dup_score = dups[0]
                        log.info(
                            "Dedup: skipping insert '%s' (similar to '%s' at %.3f)",
                            name, dup_skill.name, dup_score,
                        )
                        return dup_skill

            if existing:
                # ── Versioning: store prior body/trigger before overwrite ──
                old = self._fetch_by_name(name)
                if old:
                    self._conn.execute(
                        "UPDATE skills SET trigger=?, body=?, "
                        "prior_body=?, prior_trigger=?, updated_at=? "
                        "WHERE name=?",
                        (trigger, body, old.body, old.trigger, now, name),
                    )
                else:
                    self._conn.execute(
                        "UPDATE skills SET trigger=?, body=?, updated_at=? WHERE name=?",
                        (trigger, body, now, name),
                    )
            else:
                self._conn.execute(
                    "INSERT INTO skills (name, trigger, body, prior_body, prior_trigger, "
                    "created_at, updated_at) VALUES (?, ?, ?, NULL, NULL, ?, ?)",
                    (name, trigger, body, now, now),
                )
            self._conn.commit()
            return self._fetch_by_name(name)

    def get_by_name(self, name: str) -> Skill | None:
        """Fetch a single skill by its unique name."""
        with self._lock:
            return self._fetch_by_name(name)

    def relevant(self, query: str, k: int = 3) -> list[tuple[Skill, float]]:
        """Return top-k (Skill, blended_score) via text similarity + success rate.

        Also tries sentence-transformer embedding similarity as a
        re-ranker for low-BM25-scoring skills (if available).
        """
        with self._lock:
            all_skills = self._fetch_all()

        if not all_skills:
            return []

        # ── BM25 step ──────────────────────────────────────────────
        def text_fn(s: Skill) -> str:
            return f"{s.name} {s.trigger} {s.body[:500]}"

        bm25_results = top_k(query, all_skills, text_fn, k=len(all_skills), min_score=0.0)
        if not bm25_results:
            return []

        # ── Blend in success rate ──────────────────────────────────
        blended = []
        for skill, text_score in bm25_results:
            blended_score = self._blend_score(text_score, skill.uses, skill.successes)
            blended.append((skill, blended_score))

        # ── Semantic re-rank (if available) for low-scoring items ──
        model = _get_sentence_model()
        if model is not None and query.strip():
            try:
                query_embedding = model.encode(query)
                # Re-score skills with low blended score (< 0.2) using embedding similarity
                for i, (skill, score) in enumerate(blended):
                    if score < 0.2:
                        skill_text = text_fn(skill)
                        skill_embedding = model.encode(skill_text)
                        sem_score = _cosine_sim_vec(query_embedding, skill_embedding)
                        # Blend: 40% original BM25+success, 60% semantic
                        blended[i] = (
                            skill,
                            score * 0.4 + sem_score * 0.6,
                        )
            except Exception as exc:
                log.debug("Semantic re-rank failed: %s", exc)

        # ── Sort, apply min_score, return top-k ────────────────────
        blended.sort(key=lambda x: x[1], reverse=True)
        min_score = 0.08
        filtered = [(s, sc) for s, sc in blended if sc >= min_score]
        # Log query/score stats for min_score tuning (ring buffer, last 50)
        top_score = filtered[0][1] if filtered else 0.0
        self._query_log.append((query, top_score, len(filtered)))
        if len(self._query_log) == 1 or len(self._query_log) % 25 == 0:
            scores = [q[1] for q in self._query_log]
            hits = [q[2] for q in self._query_log]
            log.debug(
                "min_score diag: min=%.3f avg_top=%.3f max_top=%.3f avg_hits=%.1f over %d queries",
                min_score, sum(scores)/len(scores), max(scores),
                sum(hits)/len(hits), len(self._query_log),
            )
        return filtered[:k]

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

    # ── Rollback ───────────────────────────────────────────────────

    def rollback(self, name: str) -> Skill | None:
        """Restore prior_body and prior_trigger for a skill.

        Returns the restored Skill, or None if nothing to rollback.
        """
        with self._lock:
            skill = self._fetch_by_name(name)
            if not skill or (skill.prior_body is None and skill.prior_trigger is None):
                return None
            now = datetime.now(timezone.utc).isoformat()
            new_prior_body = skill.body
            new_prior_trigger = skill.trigger
            self._conn.execute(
                "UPDATE skills SET body=?, trigger=?, "
                "prior_body=?, prior_trigger=?, updated_at=? "
                "WHERE name=?",
                (
                    skill.prior_body,
                    skill.prior_trigger or skill.trigger,
                    new_prior_body,
                    new_prior_trigger,
                    now,
                    name,
                ),
            )
            self._conn.commit()
            return self._fetch_by_name(name)

    def history(self, name: str) -> list[dict]:
        """Return version history for a skill (current + prior snapshot)."""
        skill = self.get_by_name(name)
        if not skill:
            return []
        entries = [
            {
                "version": "current",
                "body": skill.body,
                "trigger": skill.trigger,
                "updated_at": skill.updated_at,
            }
        ]
        if skill.prior_body is not None:
            entries.append({
                "version": "prior",
                "body": skill.prior_body,
                "trigger": skill.prior_trigger,
                "updated_at": None,
            })
        return entries

    # ── Forgetting / Pruning ───────────────────────────────────────

    def forget(self, name: str) -> bool:
        """Delete a skill by name. Returns True if deleted."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM skills WHERE name = ?", (name,))
            self._conn.commit()
            return cur.rowcount > 0

    def prune_unused(self, days: int = 7) -> int:
        """Delete skills with 0 uses older than N days. Returns count deleted."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM skills WHERE uses = 0 AND created_at < ?",
                (cutoff,),
            )
            self._conn.commit()
            self._conn.execute("VACUUM")
        return cur.rowcount

    def prune_low_performer(
        self,
        min_uses: int = LOW_PERFORMER_MIN_USES,
        max_rate: float = LOW_PERFORMER_MAX_RATE,
    ) -> int:
        """Delete skills with many uses but low success rate.

        Args:
            min_uses: Minimum uses before considering for pruning.
            max_rate: Maximum success-rate to qualify as low-performer.

        Returns:
            Number of skills deleted.
        """
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM skills "
                "WHERE uses >= ? AND successes * 1.0 / NULLIF(uses, 0) <= ?",
                (min_uses, max_rate),
            )
            self._conn.commit()
            self._conn.execute("VACUUM")
        return cur.rowcount

    def count(self) -> int:
        """Return total number of skills."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM skills").fetchone()
        return row[0] if row else 0

    def list_skills(self) -> list[dict]:
        """Return summary of all skills (no bodies) for inspection."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT name, trigger, uses, successes, created_at, updated_at "
                "FROM skills ORDER BY uses DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self._conn.close()
