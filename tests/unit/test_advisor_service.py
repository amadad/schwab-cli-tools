import json
import sqlite3
from pathlib import Path

import pytest

from src.core.advisor_sidecar import AdvisorSidecarService
from src.schwab_client._advisor.store import AdvisorStore
from src.schwab_client.history import HistoryStore


class DummyService(AdvisorSidecarService):
    def capture_source_snapshot(self):
        snapshot = _policy_snapshot('2026-04-01T12:00:00', cash_pct=55.0)
        snapshot['history'] = {'snapshot_id': 99, 'db_path': 'history.db'}
        snapshot['market'] = {
            'signals': None,
            'vix': None,
            'indices': None,
            'sectors': None,
        }
        return snapshot

    def capture_context(self, *, include_lynch: bool = True):
        return {
            'assembled_at': '2026-04-01T12:00:00',
            'history': {'snapshot_id': 77, 'db_path': 'db.sqlite'},
            'market_available': True,
            'manual_accounts_included': False,
            'summary': {'cash_percentage': 20.0},
            'accounts': [
                {
                    'account': 'Conflicting Account (...9999)',
                    'account_alias': 'wrong_alias',
                    'total_value': 999.0,
                    'total_cash': 999.0,
                }
            ],
            'ytd_distributions': {},
            'recent_transactions': [],
            'policy_delta': {
                'alerts': [],
                'distribution_pacing': [],
                'calendar_actions': [],
                'checked_at': '2026-04-01T12:00:00',
            },
            'regime': {'regime': 'risk_off'},
            'vix': {'vix': 23.1},
        }

    def render_context_prompt(self):
        return 'Portfolio Context Block'

    def _extract_baseline_price(self, recommendation):
        return 100.0 if recommendation.target_type == 'symbol' else None

    def generate_structured_recommendation(self, prompt: str, *, model_command: str | None = None):
        return ({
            'thesis': 'Buy SPY on weakness.',
            'rationale': 'Short-term oversold, worth testing.',
            'recommendation_type': 'market',
            'target_type': 'symbol',
            'target_id': 'SPY',
            'direction': 'buy',
            'horizon_days': 5,
            'benchmark_symbol': 'SPY',
            'confidence': 0.7,
            'tags': ['oversold'],
        }, '{"thesis":"Buy SPY on weakness."}')


class MalformedRecommendationService(DummyService):
    def generate_structured_recommendation(self, prompt: str, *, model_command: str | None = None):
        return ({'target_id': 'SPY'}, '{"target_id":"SPY"}')


class EvaluationService(AdvisorSidecarService):
    pass


def _policy_snapshot(observed_at: str, *, cash_pct: float, alias: str = 'acct_test') -> dict:
    cash_value = cash_pct
    invested_value = 100.0 - cash_value
    return {
        'generated_at': observed_at,
        'portfolio': {
            'summary': {
                'total_value': 100.0,
                'api_value': 100.0,
                'manual_value': 0.0,
                'total_cash': cash_value,
                'manual_cash': 0.0,
                'total_invested': invested_value,
                'total_unrealized_pl': 0.0,
                'cash_percentage': cash_pct,
                'account_count': 1,
                'api_account_count': 1,
                'manual_account_count': 0,
                'position_count': 0,
            },
            'api_accounts': [
                {
                    'account': 'Test Account (...1234)',
                    'account_alias': alias,
                    'account_number_last4': '1234',
                    'account_type': 'IRA',
                    'total_value': 100.0,
                    'cash_balance': cash_value,
                    'money_market_value': 0.0,
                    'total_cash': cash_value,
                    'invested_value': invested_value,
                    'buying_power': 0.0,
                    'position_count': 0,
                    'positions': [],
                }
            ],
            'manual_accounts': {
                'source_path': None,
                'last_updated': None,
                'summary': {
                    'total_value': 0.0,
                    'total_cash': 0.0,
                    'total_invested': 0.0,
                    'account_count': 0,
                    'by_category': {},
                },
                'accounts': [],
            },
            'positions': [],
            'allocation': {
                'diversification_score': 100.0,
                'by_asset_type': {},
                'concentration_risks': [],
                'top_holdings_pct': [],
            },
        },
        'errors': [],
    }


def test_recommend_persists_captured_snapshot_provenance(tmp_path):
    store = AdvisorStore(tmp_path / 'advisor.db')
    service = DummyService(repo_root=Path.cwd(), store=store)
    result = service.recommend()
    run = store.get_run(result.run_id)

    assert result.run_id > 0
    assert result.snapshot_id == 99
    assert run['source_snapshot_id'] == 99
    assert run['source_history_db_path'] == 'history.db'
    assert run['baseline_state_json']['history']['snapshot_id'] == 99
    assert run['baseline_state_json']['summary']['cash_percentage'] == 55.0
    assert run['baseline_state_json']['accounts'][0]['account_alias'] == 'acct_test'
    assert run['baseline_state_json']['market_available'] is False
    assert run['market_available'] is False


def test_recommend_rejects_malformed_model_payload(tmp_path):
    store = AdvisorStore(tmp_path / 'advisor.db')
    service = MalformedRecommendationService(repo_root=Path.cwd(), store=store)

    with pytest.raises(ValueError, match='Missing required recommendation field'):
        service.recommend()


def test_evaluate_keeps_open_runs_when_horizon_not_reached(tmp_path, monkeypatch):
    history_path = tmp_path / 'history.db'
    monkeypatch.setenv('SCHWAB_HISTORY_DB_PATH', str(history_path))

    store = AdvisorStore(tmp_path / 'advisor.db')
    store.initialize()
    run_id = store.insert_recommendation_run(
        source_snapshot_id=1,
        source_history_db_path=str(history_path),
        assembled_at='2026-04-01T12:00:00',
        recommendation_type='market',
        thesis='wait here',
        rationale='vol is elevated',
        target_type='portfolio',
        target_id='portfolio',
        direction='wait',
        horizon_days=5,
        benchmark_symbol='SPY',
        baseline_price=None,
        baseline_state_json={'summary': {'cash_percentage': 40.0}},
        market_regime='risk_off',
        vix_value=24.0,
        confidence=0.7,
        tags_json=['risk_off'],
        raw_prompt='p',
        raw_response='r',
        parsed_response_json={'thesis': 'wait here'},
        status='open',
        market_available=False,
        manual_accounts_included=False,
        model_command='test-model',
    )

    payload = EvaluationService(repo_root=Path.cwd(), store=store).evaluate_open_runs()
    run = store.get_run(run_id)

    assert payload['evaluated'] == []
    assert payload['skipped'][0]['run_id'] == run_id
    assert run['status'] == 'open'
    assert run['evaluations'] == []


def test_evaluate_skips_when_distribution_history_missing(tmp_path, monkeypatch):
    history_path = tmp_path / 'history.db'
    policy_path = tmp_path / 'policy.json'
    monkeypatch.setenv('SCHWAB_HISTORY_DB_PATH', str(history_path))
    monkeypatch.setenv('SCHWAB_POLICY_PATH', str(policy_path))
    policy_path.write_text(
        json.dumps(
            {
                'inherited_ira_policies': [
                    {
                        'name': 'Inherited IRA',
                        'accounts': ['acct_test'],
                        'bucket_type': 'depletion',
                        'distribution_deadline': '2032-12-31',
                        'cash_minimum': 0,
                    }
                ],
                'cash_policies': {},
                'portfolio_cash_target': {'low': 5, 'high': 25},
                'calendar': {},
            }
        )
    )

    history = HistoryStore(history_path)
    source_meta = history.store_snapshot(
        _policy_snapshot('2026-01-01T00:00:00', cash_pct=40.0),
        source_command='snapshot',
    )
    history.store_snapshot(
        _policy_snapshot('2026-01-10T00:00:00', cash_pct=20.0),
        source_command='snapshot',
    )

    store = AdvisorStore(tmp_path / 'advisor.db')
    store.initialize()
    run_id = store.insert_recommendation_run(
        source_snapshot_id=source_meta['snapshot_id'],
        source_history_db_path=str(history_path),
        assembled_at='2026-01-01T00:00:00',
        recommendation_type='portfolio',
        thesis='Reduce idle cash.',
        rationale='Cash is above the target band.',
        target_type='account',
        target_id='acct_test',
        direction='deploy',
        horizon_days=5,
        benchmark_symbol='SPY',
        baseline_price=None,
        baseline_state_json={'summary': {'cash_percentage': 40.0}},
        market_regime='risk_off',
        vix_value=24.0,
        confidence=0.7,
        tags_json=['cash'],
        raw_prompt='p',
        raw_response='r',
        parsed_response_json={'thesis': 'Reduce idle cash.'},
        status='open',
        market_available=False,
        manual_accounts_included=False,
        model_command='test-model',
    )

    with sqlite3.connect(store.db_path) as con:
        con.execute(
            "UPDATE recommendation_runs SET created_at = ? WHERE id = ?",
            ('2026-01-01 00:00:00', run_id),
        )
        con.commit()

    payload = EvaluationService(repo_root=Path.cwd(), store=store).evaluate_open_runs()
    run = store.get_run(run_id)

    assert payload['evaluated'] == []
    assert payload['skipped'][0]['run_id'] == run_id
    assert payload['skipped'][0]['reason'].startswith('missing_distribution_history:')
    assert run['status'] == 'open'
    assert run['evaluations'] == []


def test_evaluate_marks_ignored_feedback_as_insufficient_data(tmp_path, monkeypatch):
    history_path = tmp_path / 'history.db'
    policy_path = tmp_path / 'policy.json'
    monkeypatch.setenv('SCHWAB_HISTORY_DB_PATH', str(history_path))
    monkeypatch.setenv('SCHWAB_POLICY_PATH', str(policy_path))
    policy_path.write_text(
        json.dumps(
            {
                'inherited_ira_policies': [],
                'cash_policies': {'acct_test': {'low': 10, 'high': 20}},
                'portfolio_cash_target': {'low': 5, 'high': 25},
                'calendar': {},
            }
        )
    )

    history = HistoryStore(history_path)
    source_meta = history.store_snapshot(
        _policy_snapshot('2026-01-01T00:00:00', cash_pct=40.0),
        source_command='snapshot',
    )

    store = AdvisorStore(tmp_path / 'advisor.db')
    store.initialize()
    run_id = store.insert_recommendation_run(
        source_snapshot_id=source_meta['snapshot_id'],
        source_history_db_path=str(history_path),
        assembled_at='2026-01-01T00:00:00',
        recommendation_type='portfolio',
        thesis='Reduce idle cash.',
        rationale='Cash is above the target band.',
        target_type='account',
        target_id='acct_test',
        direction='deploy',
        horizon_days=5,
        benchmark_symbol='SPY',
        baseline_price=None,
        baseline_state_json={'summary': {'cash_percentage': 40.0}},
        market_regime='risk_off',
        vix_value=24.0,
        confidence=0.7,
        tags_json=['cash'],
        raw_prompt='p',
        raw_response='r',
        parsed_response_json={'thesis': 'Reduce idle cash.'},
        status='open',
        market_available=False,
        manual_accounts_included=False,
        model_command='test-model',
    )
    store.record_feedback(run_id, status='ignored', notes='Did not act on this.')

    payload = EvaluationService(repo_root=Path.cwd(), store=store).evaluate_open_runs()
    run = store.get_run(run_id)
    evaluation = run['evaluations'][0]

    assert payload['skipped'] == []
    assert payload['evaluated'][0]['run_id'] == run_id
    assert payload['evaluated'][0]['outcome'] == 'insufficient_data'
    assert payload['evaluated'][0]['feedback_status'] == 'ignored'
    assert run['status'] == 'evaluated'
    assert evaluation['feedback_status'] == 'ignored'
    assert 'ignored by operator' in evaluation['notes'].lower()


def test_evaluate_uses_later_snapshot_policy_scores(tmp_path, monkeypatch):
    history_path = tmp_path / 'history.db'
    policy_path = tmp_path / 'policy.json'
    monkeypatch.setenv('SCHWAB_HISTORY_DB_PATH', str(history_path))
    monkeypatch.setenv('SCHWAB_POLICY_PATH', str(policy_path))
    policy_path.write_text(
        json.dumps(
            {
                'inherited_ira_policies': [],
                'cash_policies': {'acct_test': {'low': 10, 'high': 20}},
                'portfolio_cash_target': {'low': 5, 'high': 25},
                'calendar': {},
            }
        )
    )

    history = HistoryStore(history_path)
    source_meta = history.store_snapshot(
        _policy_snapshot('2026-01-01T00:00:00', cash_pct=40.0),
        source_command='snapshot',
    )
    later_meta = history.store_snapshot(
        _policy_snapshot('2026-01-10T00:00:00', cash_pct=20.0),
        source_command='snapshot',
    )

    store = AdvisorStore(tmp_path / 'advisor.db')
    store.initialize()
    run_id = store.insert_recommendation_run(
        source_snapshot_id=source_meta['snapshot_id'],
        source_history_db_path=str(history_path),
        assembled_at='2026-01-01T00:00:00',
        recommendation_type='portfolio',
        thesis='Reduce idle cash.',
        rationale='Cash is above the target band.',
        target_type='account',
        target_id='acct_test',
        direction='deploy',
        horizon_days=5,
        benchmark_symbol='SPY',
        baseline_price=None,
        baseline_state_json={'summary': {'cash_percentage': 40.0}},
        market_regime='risk_off',
        vix_value=24.0,
        confidence=0.7,
        tags_json=['cash'],
        raw_prompt='p',
        raw_response='r',
        parsed_response_json={'thesis': 'Reduce idle cash.'},
        status='open',
        market_available=False,
        manual_accounts_included=False,
        model_command='test-model',
    )

    with sqlite3.connect(store.db_path) as con:
        con.execute(
            "UPDATE recommendation_runs SET created_at = ? WHERE id = ?",
            ('2026-01-01 00:00:00', run_id),
        )
        con.commit()

    payload = EvaluationService(repo_root=Path.cwd(), store=store).evaluate_open_runs()
    run = store.get_run(run_id)
    evaluation = run['evaluations'][0]

    assert payload['evaluated'][0]['run_id'] == run_id
    assert payload['evaluated'][0]['evaluation_snapshot_id'] == later_meta['snapshot_id']
    assert payload['evaluated'][0]['outcome'] == 'improved'
    assert payload['skipped'] == []
    assert run['status'] == 'evaluated'
    assert evaluation['evaluation_snapshot_id'] == later_meta['snapshot_id']
    assert evaluation['policy_score_after'] > evaluation['policy_score_before']
