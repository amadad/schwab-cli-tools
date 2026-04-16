from src.core.advisor_scoring import classify_outcome, compute_policy_health_score
from src.core.context import PortfolioContext


def test_compute_policy_health_score_penalizes_warnings():
    score = compute_policy_health_score(
        {
            "policy_delta": {
                "alerts": [{"severity": "warning"}, {"severity": "info"}],
                "distribution_pacing": [{"on_track": False}],
            }
        }
    )
    assert score < 100


def test_compute_policy_health_score_requires_policy_delta():
    assert compute_policy_health_score({"summary": {"snapshot_id": 1}}) is None


def test_compute_policy_health_score_accepts_portfolio_context():
    score = compute_policy_health_score(
        PortfolioContext.from_dict(
            {
                "policy_delta": {
                    "alerts": [{"severity": "warning"}],
                    "distribution_pacing": [],
                    "calendar_actions": [],
                    "checked_at": "2026-04-16T00:00:00",
                },
                "summary": {"cash_percentage": 24.0},
                "assembled_at": "2026-04-16T00:00:00",
            }
        )
    )
    assert score == 90.0


def test_compute_policy_health_score_ignores_invalid_cash_percentage():
    score = compute_policy_health_score(
        {
            "policy_delta": {"alerts": [], "distribution_pacing": []},
            "summary": {"cash_percentage": "not-a-number"},
        }
    )
    assert score == 100.0


def test_classify_outcome():
    assert classify_outcome(50, 60)[1] == "improved"
    assert classify_outcome(60, 50)[1] == "worsened"
    assert classify_outcome(60, 62)[1] == "neutral"
