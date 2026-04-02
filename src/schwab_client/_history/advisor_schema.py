"""Schema for the portfolio advisor learning loop.

Tables:
- theses: Investment theses with entry context (regime, signals, rationale)
- thesis_checkpoints: Periodic outcome measurements against theses
- thesis_reviews: Retrospective analysis of closed/matured theses
- signal_patterns: Extracted patterns from thesis outcomes (what worked, what didn't)
- research_scans: Auto-research scan results using learned patterns
"""

from __future__ import annotations

ADVISOR_SCHEMA_STATEMENTS = [
    # --- Theses ---
    """
    CREATE TABLE IF NOT EXISTS theses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL DEFAULT 'long',
        status TEXT NOT NULL DEFAULT 'open',
        rationale TEXT NOT NULL,
        time_horizon_days INTEGER NOT NULL DEFAULT 90,
        entry_price REAL,
        target_return_pct REAL,
        stop_loss_pct REAL,
        regime_at_entry TEXT,
        vix_at_entry REAL,
        sentiment_at_entry TEXT,
        sector_rotation_at_entry TEXT,
        signals_json TEXT,
        tags TEXT,
        opened_at TEXT NOT NULL,
        closed_at TEXT,
        close_reason TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_theses_symbol ON theses(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_theses_status ON theses(status)",
    "CREATE INDEX IF NOT EXISTS idx_theses_opened_at ON theses(opened_at DESC)",

    # --- Checkpoints (periodic outcome measurements) ---
    """
    CREATE TABLE IF NOT EXISTS thesis_checkpoints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thesis_id INTEGER NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
        checked_at TEXT NOT NULL,
        current_price REAL,
        return_pct REAL,
        regime_current TEXT,
        vix_current REAL,
        sentiment_current TEXT,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_checkpoints_thesis ON thesis_checkpoints(thesis_id)",
    "CREATE INDEX IF NOT EXISTS idx_checkpoints_date ON thesis_checkpoints(checked_at DESC)",

    # --- Reviews (retrospective analysis) ---
    """
    CREATE TABLE IF NOT EXISTS thesis_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thesis_id INTEGER NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
        final_return_pct REAL,
        was_correct INTEGER,
        regime_aligned INTEGER,
        what_worked TEXT,
        what_failed TEXT,
        lessons TEXT,
        regime_trajectory TEXT,
        reviewed_at TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(thesis_id)
    )
    """,

    # --- Signal Patterns (extracted learnings) ---
    """
    CREATE TABLE IF NOT EXISTS signal_patterns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pattern_name TEXT NOT NULL UNIQUE,
        description TEXT,
        conditions_json TEXT NOT NULL,
        sample_size INTEGER NOT NULL DEFAULT 0,
        hit_rate REAL,
        avg_return_pct REAL,
        median_return_pct REAL,
        best_return_pct REAL,
        worst_return_pct REAL,
        avg_holding_days REAL,
        regime_affinity TEXT,
        last_updated TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # --- Research Scans (auto-generated candidate lists) ---
    """
    CREATE TABLE IF NOT EXISTS research_scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_name TEXT,
        scanned_at TEXT NOT NULL,
        regime_at_scan TEXT,
        criteria_json TEXT NOT NULL,
        candidates_json TEXT NOT NULL,
        candidate_count INTEGER NOT NULL DEFAULT 0,
        patterns_used TEXT,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_scans_date ON research_scans(scanned_at DESC)",

    # --- Convenience views ---
    """
    CREATE VIEW IF NOT EXISTS open_theses AS
    SELECT
        t.id,
        t.symbol,
        t.direction,
        t.rationale,
        t.time_horizon_days,
        t.entry_price,
        t.target_return_pct,
        t.stop_loss_pct,
        t.regime_at_entry,
        t.vix_at_entry,
        t.tags,
        t.opened_at,
        julianday('now') - julianday(t.opened_at) AS days_open,
        (SELECT cp.return_pct FROM thesis_checkpoints cp
         WHERE cp.thesis_id = t.id ORDER BY cp.checked_at DESC LIMIT 1
        ) AS latest_return_pct,
        (SELECT cp.checked_at FROM thesis_checkpoints cp
         WHERE cp.thesis_id = t.id ORDER BY cp.checked_at DESC LIMIT 1
        ) AS last_checked
    FROM theses t
    WHERE t.status = 'open'
    ORDER BY t.opened_at DESC
    """,

    """
    CREATE VIEW IF NOT EXISTS thesis_performance AS
    SELECT
        t.id,
        t.symbol,
        t.direction,
        t.status,
        t.regime_at_entry,
        t.vix_at_entry,
        t.opened_at,
        t.closed_at,
        t.time_horizon_days,
        r.final_return_pct,
        r.was_correct,
        r.regime_aligned,
        r.lessons,
        julianday(COALESCE(t.closed_at, 'now')) - julianday(t.opened_at) AS holding_days
    FROM theses t
    LEFT JOIN thesis_reviews r ON r.thesis_id = t.id
    ORDER BY t.opened_at DESC
    """,

    """
    CREATE VIEW IF NOT EXISTS pattern_leaderboard AS
    SELECT
        pattern_name,
        hit_rate,
        avg_return_pct,
        sample_size,
        regime_affinity,
        last_updated
    FROM signal_patterns
    WHERE sample_size >= 3
    ORDER BY hit_rate * avg_return_pct DESC
    """,
]
