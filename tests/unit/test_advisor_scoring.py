from src.core.advisor_scoring import classify_outcome, compute_policy_health_score


def test_compute_policy_health_score_penalizes_warnings():
    score = compute_policy_health_score({
        'policy_delta': {
            'alerts': [{'severity': 'warning'}, {'severity': 'info'}],
            'distribution_pacing': [{'on_track': False}],
        }
    })
    assert score < 100


def test_compute_policy_health_score_requires_policy_delta():
    assert compute_policy_health_score({'summary': {'snapshot_id': 1}}) is None


def test_classify_outcome():
    assert classify_outcome(50, 60)[1] == 'improved'
    assert classify_outcome(60, 50)[1] == 'worsened'
    assert classify_outcome(60, 62)[1] == 'neutral'
