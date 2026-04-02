"""SQLite-backed store for the portfolio advisor learning loop."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .advisor_schema import ADVISOR_SCHEMA_STATEMENTS
from .schema import resolve_history_db_path


class AdvisorStore:
    """Persist and query advisor learning loop data.

    Uses the same SQLite database as HistoryStore (snapshot history),
    adding advisor-specific tables alongside the existing ones.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser() if path else resolve_history_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        with self._connect() as conn:
            for statement in ADVISOR_SCHEMA_STATEMENTS:
                conn.execute(statement)
            conn.commit()

    def _connect(self, *, query_only: bool = False) -> sqlite3.Connection:
        if query_only and self.path.exists():
            conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        else:
            conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if query_only:
            conn.execute("PRAGMA query_only = ON")
        return conn

    def _fetch_all(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._connect(query_only=True) as conn:
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    # ── Thesis CRUD ──────────────────────────────────────────────────

    def record_thesis(
        self,
        *,
        symbol: str,
        direction: str = "long",
        rationale: str,
        time_horizon_days: int = 90,
        entry_price: float | None = None,
        target_return_pct: float | None = None,
        stop_loss_pct: float | None = None,
        regime: str | None = None,
        vix: float | None = None,
        sentiment: str | None = None,
        sector_rotation: str | None = None,
        signals: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Record a new investment thesis with full entry context."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO theses (
                    symbol, direction, status, rationale, time_horizon_days,
                    entry_price, target_return_pct, stop_loss_pct,
                    regime_at_entry, vix_at_entry, sentiment_at_entry,
                    sector_rotation_at_entry, signals_json, tags, opened_at
                ) VALUES (?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol.upper(),
                    direction,
                    rationale,
                    time_horizon_days,
                    entry_price,
                    target_return_pct,
                    stop_loss_pct,
                    regime,
                    vix,
                    sentiment,
                    sector_rotation,
                    json.dumps(signals) if signals else None,
                    ",".join(tags) if tags else None,
                    now,
                ),
            )
            conn.commit()
            thesis_id = cursor.lastrowid

        return {"thesis_id": thesis_id, "symbol": symbol.upper(), "opened_at": now}

    def close_thesis(
        self,
        thesis_id: int,
        *,
        reason: str = "manual",
    ) -> dict[str, Any]:
        """Close an open thesis."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE theses SET status = 'closed', closed_at = ?, close_reason = ? WHERE id = ?",
                (now, reason, thesis_id),
            )
            conn.commit()
        return {"thesis_id": thesis_id, "status": "closed", "closed_at": now}

    def get_thesis(self, thesis_id: int) -> dict[str, Any] | None:
        """Get a single thesis by ID."""
        rows = self._fetch_all("SELECT * FROM theses WHERE id = ?", (thesis_id,))
        return rows[0] if rows else None

    def list_theses(
        self,
        *,
        status: str | None = "open",
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List theses with optional filters."""
        sql = "SELECT * FROM theses"
        clauses: list[str] = []
        params: list[Any] = []

        if status:
            clauses.append("status = ?")
            params.append(status)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY opened_at DESC LIMIT ?"
        params.append(limit)
        return self._fetch_all(sql, params)

    def get_open_theses(self) -> list[dict[str, Any]]:
        """Get all open theses (convenience view)."""
        return self._fetch_all("SELECT * FROM open_theses")

    # ── Checkpoints ──────────────────────────────────────────────────

    def record_checkpoint(
        self,
        thesis_id: int,
        *,
        current_price: float | None = None,
        return_pct: float | None = None,
        regime: str | None = None,
        vix: float | None = None,
        sentiment: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Record a checkpoint measurement for a thesis."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO thesis_checkpoints (
                    thesis_id, checked_at, current_price, return_pct,
                    regime_current, vix_current, sentiment_current, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (thesis_id, now, current_price, return_pct, regime, vix, sentiment, notes),
            )
            conn.commit()
            return {"checkpoint_id": cursor.lastrowid, "thesis_id": thesis_id, "checked_at": now}

    def get_checkpoints(self, thesis_id: int) -> list[dict[str, Any]]:
        """Get all checkpoints for a thesis, most recent first."""
        return self._fetch_all(
            "SELECT * FROM thesis_checkpoints WHERE thesis_id = ? ORDER BY checked_at DESC",
            (thesis_id,),
        )

    # ── Reviews ──────────────────────────────────────────────────────

    def record_review(
        self,
        thesis_id: int,
        *,
        final_return_pct: float | None = None,
        was_correct: bool | None = None,
        regime_aligned: bool | None = None,
        what_worked: str | None = None,
        what_failed: str | None = None,
        lessons: str | None = None,
        regime_trajectory: str | None = None,
    ) -> dict[str, Any]:
        """Record a retrospective review for a thesis."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO thesis_reviews (
                    thesis_id, final_return_pct, was_correct, regime_aligned,
                    what_worked, what_failed, lessons, regime_trajectory, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thesis_id) DO UPDATE SET
                    final_return_pct = excluded.final_return_pct,
                    was_correct = excluded.was_correct,
                    regime_aligned = excluded.regime_aligned,
                    what_worked = excluded.what_worked,
                    what_failed = excluded.what_failed,
                    lessons = excluded.lessons,
                    regime_trajectory = excluded.regime_trajectory,
                    reviewed_at = excluded.reviewed_at
                """,
                (
                    thesis_id,
                    final_return_pct,
                    int(was_correct) if was_correct is not None else None,
                    int(regime_aligned) if regime_aligned is not None else None,
                    what_worked,
                    what_failed,
                    lessons,
                    regime_trajectory,
                    now,
                ),
            )
            conn.commit()
        return {"thesis_id": thesis_id, "reviewed_at": now}

    def get_review(self, thesis_id: int) -> dict[str, Any] | None:
        """Get the review for a thesis."""
        rows = self._fetch_all(
            "SELECT * FROM thesis_reviews WHERE thesis_id = ?", (thesis_id,)
        )
        return rows[0] if rows else None

    # ── Signal Patterns ──────────────────────────────────────────────

    def upsert_pattern(
        self,
        *,
        pattern_name: str,
        description: str | None = None,
        conditions: dict[str, Any],
        sample_size: int = 0,
        hit_rate: float | None = None,
        avg_return_pct: float | None = None,
        median_return_pct: float | None = None,
        best_return_pct: float | None = None,
        worst_return_pct: float | None = None,
        avg_holding_days: float | None = None,
        regime_affinity: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a signal pattern."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO signal_patterns (
                    pattern_name, description, conditions_json,
                    sample_size, hit_rate, avg_return_pct, median_return_pct,
                    best_return_pct, worst_return_pct, avg_holding_days,
                    regime_affinity, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pattern_name) DO UPDATE SET
                    description = excluded.description,
                    conditions_json = excluded.conditions_json,
                    sample_size = excluded.sample_size,
                    hit_rate = excluded.hit_rate,
                    avg_return_pct = excluded.avg_return_pct,
                    median_return_pct = excluded.median_return_pct,
                    best_return_pct = excluded.best_return_pct,
                    worst_return_pct = excluded.worst_return_pct,
                    avg_holding_days = excluded.avg_holding_days,
                    regime_affinity = excluded.regime_affinity,
                    last_updated = excluded.last_updated
                """,
                (
                    pattern_name,
                    description,
                    json.dumps(conditions),
                    sample_size,
                    hit_rate,
                    avg_return_pct,
                    median_return_pct,
                    best_return_pct,
                    worst_return_pct,
                    avg_holding_days,
                    regime_affinity,
                    now,
                ),
            )
            conn.commit()
        return {"pattern_name": pattern_name, "last_updated": now}

    def get_patterns(self, *, min_sample_size: int = 0) -> list[dict[str, Any]]:
        """Get all signal patterns, optionally filtered by sample size."""
        return self._fetch_all(
            """
            SELECT * FROM signal_patterns
            WHERE sample_size >= ?
            ORDER BY hit_rate * COALESCE(avg_return_pct, 0) DESC
            """,
            (min_sample_size,),
        )

    def get_pattern_leaderboard(self) -> list[dict[str, Any]]:
        """Get patterns ranked by effectiveness (sample_size >= 3)."""
        return self._fetch_all("SELECT * FROM pattern_leaderboard")

    # ── Research Scans ───────────────────────────────────────────────

    def record_scan(
        self,
        *,
        scan_name: str | None = None,
        regime: str | None = None,
        criteria: dict[str, Any],
        candidates: list[dict[str, Any]],
        patterns_used: list[str] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Record a research scan result."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO research_scans (
                    scan_name, scanned_at, regime_at_scan,
                    criteria_json, candidates_json, candidate_count,
                    patterns_used, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scan_name,
                    now,
                    regime,
                    json.dumps(criteria),
                    json.dumps(candidates),
                    len(candidates),
                    ",".join(patterns_used) if patterns_used else None,
                    notes,
                ),
            )
            conn.commit()
            return {"scan_id": cursor.lastrowid, "scanned_at": now, "candidate_count": len(candidates)}

    def get_recent_scans(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent research scans."""
        return self._fetch_all(
            "SELECT * FROM research_scans ORDER BY scanned_at DESC LIMIT ?",
            (limit,),
        )

    # ── Aggregate analytics ──────────────────────────────────────────

    def get_performance_summary(self) -> dict[str, Any]:
        """Get aggregate performance stats across all theses."""
        with self._connect(query_only=True) as conn:
            total = conn.execute("SELECT COUNT(*) as n FROM theses").fetchone()["n"]
            open_count = conn.execute(
                "SELECT COUNT(*) as n FROM theses WHERE status = 'open'"
            ).fetchone()["n"]
            closed = conn.execute(
                "SELECT COUNT(*) as n FROM theses WHERE status = 'closed'"
            ).fetchone()["n"]

            reviewed = conn.execute(
                "SELECT COUNT(*) as n FROM thesis_reviews"
            ).fetchone()["n"]

            # Win rate from reviews
            wins = conn.execute(
                "SELECT COUNT(*) as n FROM thesis_reviews WHERE was_correct = 1"
            ).fetchone()["n"]

            avg_return = conn.execute(
                "SELECT AVG(final_return_pct) as avg_ret FROM thesis_reviews WHERE final_return_pct IS NOT NULL"
            ).fetchone()["avg_ret"]

            # By regime
            regime_stats = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT
                        t.regime_at_entry AS regime,
                        COUNT(*) AS thesis_count,
                        SUM(CASE WHEN r.was_correct = 1 THEN 1 ELSE 0 END) AS wins,
                        AVG(r.final_return_pct) AS avg_return
                    FROM theses t
                    LEFT JOIN thesis_reviews r ON r.thesis_id = t.id
                    WHERE t.regime_at_entry IS NOT NULL
                    GROUP BY t.regime_at_entry
                    """
                ).fetchall()
            ]

            pattern_count = conn.execute(
                "SELECT COUNT(*) as n FROM signal_patterns"
            ).fetchone()["n"]

        return {
            "total_theses": total,
            "open": open_count,
            "closed": closed,
            "reviewed": reviewed,
            "win_rate": wins / reviewed if reviewed > 0 else None,
            "avg_return_pct": avg_return,
            "by_regime": regime_stats,
            "patterns_extracted": pattern_count,
        }

    def get_thesis_with_history(self, thesis_id: int) -> dict[str, Any] | None:
        """Get a thesis with its full checkpoint and review history."""
        thesis = self.get_thesis(thesis_id)
        if not thesis:
            return None

        thesis["checkpoints"] = self.get_checkpoints(thesis_id)
        thesis["review"] = self.get_review(thesis_id)

        if thesis.get("signals_json"):
            try:
                thesis["signals"] = json.loads(thesis["signals_json"])
            except (json.JSONDecodeError, TypeError):
                thesis["signals"] = None

        return thesis

    def get_learning_context(self) -> dict[str, Any]:
        """Assemble the full learning context for LLM consumption.

        Returns everything needed for the LLM to generate retrospectives,
        extract patterns, and recommend research directions.
        """
        performance = self.get_performance_summary()
        open_theses = self.get_open_theses()
        recent_reviews = self._fetch_all(
            """
            SELECT t.symbol, t.direction, t.regime_at_entry, t.vix_at_entry,
                   r.final_return_pct, r.was_correct, r.lessons, r.regime_trajectory
            FROM thesis_reviews r
            JOIN theses t ON t.id = r.thesis_id
            ORDER BY r.reviewed_at DESC
            LIMIT 20
            """,
        )
        patterns = self.get_patterns(min_sample_size=0)
        recent_scans = self.get_recent_scans(limit=5)

        return {
            "performance": performance,
            "open_theses": open_theses,
            "recent_reviews": recent_reviews,
            "patterns": patterns,
            "recent_scans": recent_scans,
        }
