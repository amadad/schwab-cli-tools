from src.schwab_client._advisor.store import AdvisorStore


def test_advisor_store_initializes_db(tmp_path):
    store = AdvisorStore(tmp_path / 'advisor.db')
    db_path = store.initialize()
    status = store.status()
    assert db_path.exists()
    assert status['run_count'] == 0


def test_store_round_trip(tmp_path):
    store = AdvisorStore(tmp_path / 'advisor.db')
    store.initialize()
    run_id = store.insert_recommendation_run(
        source_snapshot_id=1,
        source_history_db_path='db.sqlite',
        recommendation_type='market',
        thesis='wait here',
        rationale='vol is elevated',
        target_type='portfolio',
        target_id='portfolio',
        direction='wait',
        horizon_days=5,
        benchmark_symbol='SPY',
        baseline_price=None,
        baseline_state_json={'x': 1},
        market_regime='risk_off',
        vix_value=24.0,
        confidence=0.7,
        tags_json=['risk_off'],
        raw_prompt='p',
        raw_response='r',
        parsed_response_json={'thesis': 'wait here'},
        status='open',
    )
    store.record_feedback(run_id, status='followed', notes='ok')
    store.record_note(run_id, body='good instinct')
    store.insert_evaluation(run_id, horizon_days=5, outcome='mixed', notes='flat')
    run = store.get_run(run_id)
    assert run['thesis'] == 'wait here'
    assert len(run['feedback']) == 1
    assert len(run['notes']) == 1
    assert len(run['evaluations']) == 1
