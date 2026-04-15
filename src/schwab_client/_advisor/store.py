"""Persistence layer for the advisor sidecar."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .schema import SCHEMA_STATEMENTS, resolve_advisor_db_path

RECOMMENDATION_RUN_COLUMN_MIGRATIONS = {
    "assembled_at": "TEXT",
    "market_available": "INTEGER NOT NULL DEFAULT 0",
    "manual_accounts_included": "INTEGER NOT NULL DEFAULT 0",
    "model_command": "TEXT",
    "issue_key": "TEXT",
    "novelty_hash": "TEXT",
    "prompt_version": "TEXT",
    "why_now_class": "TEXT",
    "supersedes_run_id": "INTEGER",
}

RECOMMENDATION_EVALUATION_COLUMN_MIGRATIONS = {
    "evaluation_snapshot_id": "INTEGER",
    "policy_score_before": "REAL",
    "policy_score_after": "REAL",
    "delta_score": "REAL",
    "feedback_status": "TEXT",
}


class AdvisorStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = resolve_advisor_db_path(db_path)

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def initialize(self) -> Path:
        with self.connect() as con:
            for statement in SCHEMA_STATEMENTS:
                con.execute(statement)
            self._ensure_columns(
                con,
                "recommendation_runs",
                RECOMMENDATION_RUN_COLUMN_MIGRATIONS,
            )
            self._ensure_columns(
                con,
                "recommendation_evaluations",
                RECOMMENDATION_EVALUATION_COLUMN_MIGRATIONS,
            )
            self._ensure_indexes(con)
            con.commit()
        return self.db_path

    def _ensure_columns(
        self,
        con: sqlite3.Connection,
        table: str,
        columns: dict[str, str],
    ) -> None:
        existing = {
            row[1]
            for row in con.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, definition in columns.items():
            if name not in existing:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def _ensure_indexes(self, con: sqlite3.Connection) -> None:
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_recommendation_runs_issue_key ON recommendation_runs(issue_key)"
        )

    def insert_recommendation_run(self, **kwargs: Any) -> int:
        fields = [
            "assembled_at",
            "source_snapshot_id",
            "source_history_db_path",
            "recommendation_type",
            "thesis",
            "rationale",
            "target_type",
            "target_id",
            "direction",
            "horizon_days",
            "benchmark_symbol",
            "baseline_price",
            "baseline_state_json",
            "market_regime",
            "vix_value",
            "confidence",
            "tags_json",
            "raw_prompt",
            "raw_response",
            "parsed_response_json",
            "market_available",
            "manual_accounts_included",
            "model_command",
            "issue_key",
            "novelty_hash",
            "prompt_version",
            "why_now_class",
            "supersedes_run_id",
            "status",
        ]
        payload = {k: kwargs.get(k) for k in fields}
        if isinstance(payload.get("baseline_state_json"), dict | list):
            payload["baseline_state_json"] = json.dumps(payload["baseline_state_json"])
        if isinstance(payload.get("tags_json"), dict | list):
            payload["tags_json"] = json.dumps(payload["tags_json"])
        if isinstance(payload.get("parsed_response_json"), dict | list):
            payload["parsed_response_json"] = json.dumps(payload["parsed_response_json"])
        payload.setdefault("status", "open")
        payload["market_available"] = int(bool(payload.get("market_available", False)))
        payload["manual_accounts_included"] = int(
            bool(payload.get("manual_accounts_included", False))
        )
        cols = ", ".join(fields)
        qs = ", ".join(["?"] * len(fields))
        with self.connect() as con:
            cur = con.execute(
                f"INSERT INTO recommendation_runs ({cols}) VALUES ({qs})",
                [payload[f] for f in fields],
            )
            con.commit()
            if cur.lastrowid is None:
                raise RuntimeError("Could not determine inserted recommendation run id")
            return int(cur.lastrowid)

    def list_open_runs(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute("SELECT id FROM recommendation_runs WHERE status='open' ORDER BY created_at ASC, id ASC").fetchall()
        return [{"id": int(r[0])} for r in rows]

    def find_open_run_by_issue_key(self, issue_key: str | None) -> dict[str, Any] | None:
        if not issue_key:
            return None
        with self.connect() as con:
            row = con.execute(
                "SELECT id FROM recommendation_runs WHERE status='open' AND issue_key = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (issue_key,),
            ).fetchone()
        if row is None:
            return None
        return self.get_run(int(row[0]))

    def record_feedback(self, run_id: int, *, status: str, notes: str | None = None) -> None:
        with self.connect() as con:
            con.execute("INSERT INTO recommendation_feedback (run_id, status, notes) VALUES (?, ?, ?)", (run_id, status, notes))
            con.commit()

    def record_note(self, run_id: int, *, body: str, note_type: str = "lesson") -> None:
        with self.connect() as con:
            con.execute("INSERT INTO recommendation_notes (run_id, note_type, body) VALUES (?, ?, ?)", (run_id, note_type, body))
            con.commit()

    def insert_evaluation(self, run_id: int, **kwargs: Any) -> None:
        fields = [
            "evaluation_snapshot_id",
            "horizon_days",
            "price_then",
            "price_now",
            "benchmark_then",
            "benchmark_now",
            "absolute_return",
            "benchmark_return",
            "excess_return",
            "policy_score_before",
            "policy_score_after",
            "delta_score",
            "feedback_status",
            "outcome",
            "notes",
        ]
        vals = [kwargs.get(f) for f in fields]
        with self.connect() as con:
            con.execute(
                f"INSERT INTO recommendation_evaluations (run_id, {', '.join(fields)}) VALUES (?, {', '.join(['?'] * len(fields))})",
                [run_id, *vals],
            )
            con.execute("UPDATE recommendation_runs SET status='evaluated' WHERE id=?", (run_id,))
            con.commit()

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM recommendation_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                return None
            feedback = [dict(r) for r in con.execute("SELECT * FROM recommendation_feedback WHERE run_id=? ORDER BY recorded_at DESC, id DESC", (run_id,)).fetchall()]
            evaluations = [dict(r) for r in con.execute("SELECT * FROM recommendation_evaluations WHERE run_id=? ORDER BY evaluated_at DESC, id DESC", (run_id,)).fetchall()]
            notes = [dict(r) for r in con.execute("SELECT * FROM recommendation_notes WHERE run_id=? ORDER BY created_at DESC, id DESC", (run_id,)).fetchall()]
        run = dict(row)
        for field in ["baseline_state_json", "tags_json", "parsed_response_json"]:
            if run.get(field):
                run[field] = json.loads(run[field])
        run["market_available"] = bool(run.get("market_available", 0))
        run["manual_accounts_included"] = bool(run.get("manual_accounts_included", 0))
        run["feedback"] = feedback
        run["evaluations"] = evaluations
        run["notes"] = notes
        return run

    def status(self) -> dict[str, Any]:
        with self.connect() as con:
            run_count = con.execute("SELECT COUNT(*) FROM recommendation_runs").fetchone()[0]
            open_count = con.execute("SELECT COUNT(*) FROM recommendation_runs WHERE status='open'").fetchone()[0]
            eval_count = con.execute("SELECT COUNT(*) FROM recommendation_evaluations").fetchone()[0]
            recent = [dict(r) for r in con.execute("SELECT id, created_at, thesis, recommendation_type, target_id, direction, horizon_days, status FROM recommendation_runs ORDER BY created_at DESC, id DESC LIMIT 10").fetchall()]
        return {
            "db_path": str(self.db_path),
            "initialized": self.db_path.exists(),
            "run_count": run_count,
            "open_count": open_count,
            "evaluation_count": eval_count,
            "recent_runs": recent,
        }
