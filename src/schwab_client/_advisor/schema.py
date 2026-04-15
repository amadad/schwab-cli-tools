"""Schema and path helpers for the advisor sidecar store."""

from __future__ import annotations

import os
from pathlib import Path

ADVISOR_DB_ENV_VAR = "SCHWAB_ADVISOR_DB_PATH"


def resolve_advisor_db_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    env_path = os.getenv(ADVISOR_DB_ENV_VAR)
    if env_path:
        return Path(env_path).expanduser()
    return Path.cwd() / "private" / "advisor" / "advisor.db"


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS recommendation_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        assembled_at TEXT,
        source_snapshot_id INTEGER,
        source_history_db_path TEXT,
        recommendation_type TEXT NOT NULL DEFAULT 'portfolio',
        thesis TEXT NOT NULL,
        rationale TEXT,
        target_type TEXT,
        target_id TEXT,
        direction TEXT,
        horizon_days INTEGER,
        benchmark_symbol TEXT,
        baseline_price REAL,
        baseline_state_json TEXT,
        market_regime TEXT,
        vix_value REAL,
        confidence REAL,
        tags_json TEXT,
        raw_prompt TEXT,
        raw_response TEXT,
        parsed_response_json TEXT,
        market_available INTEGER NOT NULL DEFAULT 0,
        manual_accounts_included INTEGER NOT NULL DEFAULT 0,
        model_command TEXT,
        issue_key TEXT,
        novelty_hash TEXT,
        prompt_version TEXT,
        why_now_class TEXT,
        supersedes_run_id INTEGER,
        status TEXT NOT NULL DEFAULT 'open'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recommendation_evaluations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES recommendation_runs(id) ON DELETE CASCADE,
        evaluated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        evaluation_snapshot_id INTEGER,
        horizon_days INTEGER,
        price_then REAL,
        price_now REAL,
        benchmark_then REAL,
        benchmark_now REAL,
        absolute_return REAL,
        benchmark_return REAL,
        excess_return REAL,
        policy_score_before REAL,
        policy_score_after REAL,
        delta_score REAL,
        feedback_status TEXT,
        outcome TEXT NOT NULL,
        notes TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recommendation_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES recommendation_runs(id) ON DELETE CASCADE,
        recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        status TEXT NOT NULL,
        notes TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recommendation_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES recommendation_runs(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        note_type TEXT NOT NULL DEFAULT 'lesson',
        body TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_recommendation_runs_status ON recommendation_runs(status)",
    "CREATE INDEX IF NOT EXISTS idx_recommendation_runs_created_at ON recommendation_runs(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_recommendation_evaluations_run_id ON recommendation_evaluations(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_recommendation_feedback_run_id ON recommendation_feedback(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_recommendation_notes_run_id ON recommendation_notes(run_id)",
]
