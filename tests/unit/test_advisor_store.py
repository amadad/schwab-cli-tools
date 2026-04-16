import sqlite3

from src.schwab_client._advisor.store import AdvisorStore


def test_advisor_store_initializes_db(tmp_path):
    store = AdvisorStore(tmp_path / "advisor.db")
    db_path = store.initialize()
    status = store.status()
    assert db_path.exists()
    assert status["run_count"] == 0


def test_advisor_store_migrates_legacy_db_before_indexing_issue_key(tmp_path):
    db_path = tmp_path / "advisor.db"
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE recommendation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
                status TEXT NOT NULL DEFAULT 'open'
            )
            """
        )
        con.execute(
            """
            CREATE TABLE recommendation_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                evaluated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                outcome TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE recommendation_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL,
                notes TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE recommendation_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                note_type TEXT NOT NULL DEFAULT 'lesson',
                body TEXT NOT NULL
            )
            """
        )
        con.commit()
    finally:
        con.close()

    store = AdvisorStore(db_path)
    store.initialize()
    run_id = store.insert_recommendation_run(
        source_snapshot_id=1,
        source_history_db_path="db.sqlite",
        recommendation_type="market",
        thesis="wait here",
        rationale="vol is elevated",
        target_type="portfolio",
        target_id="portfolio",
        direction="wait",
        horizon_days=5,
        benchmark_symbol="SPY",
        baseline_price=None,
        baseline_state_json={"x": 1},
        market_regime="risk_off",
        vix_value=24.0,
        confidence=0.7,
        tags_json=["risk_off"],
        raw_prompt="p",
        raw_response="r",
        parsed_response_json={"thesis": "wait here"},
        issue_key="market:portfolio:portfolio:wait",
        status="open",
    )

    run = store.find_open_run_by_issue_key("market:portfolio:portfolio:wait")
    assert run is not None
    assert run["id"] == run_id
    assert run["issue_key"] == "market:portfolio:portfolio:wait"


def test_store_round_trip(tmp_path):
    store = AdvisorStore(tmp_path / "advisor.db")
    store.initialize()
    run_id = store.insert_recommendation_run(
        source_snapshot_id=1,
        source_history_db_path="db.sqlite",
        recommendation_type="market",
        thesis="wait here",
        rationale="vol is elevated",
        target_type="portfolio",
        target_id="portfolio",
        direction="wait",
        horizon_days=5,
        benchmark_symbol="SPY",
        baseline_price=None,
        baseline_state_json={"x": 1},
        market_regime="risk_off",
        vix_value=24.0,
        confidence=0.7,
        tags_json=["risk_off"],
        raw_prompt="p",
        raw_response="r",
        parsed_response_json={"thesis": "wait here"},
        status="open",
    )
    store.record_feedback(run_id, status="followed", notes="ok")
    store.record_note(run_id, body="good instinct")
    store.insert_evaluation(run_id, horizon_days=5, outcome="mixed", notes="flat")
    run = store.get_run(run_id)
    assert run["thesis"] == "wait here"
    assert len(run["feedback"]) == 1
    assert len(run["notes"]) == 1
    assert len(run["evaluations"]) == 1
