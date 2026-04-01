"""Tests for externalized portfolio policy loading."""

import json
from datetime import date

from src.core.policy import (
    DEFAULT_POLICY_TEMPLATE_PATH,
    PolicyConfig,
    evaluate_policy,
    load_policy_config,
)


class TestPolicyConfigLoading:
    """Tests for policy profile resolution and parsing."""

    def test_load_policy_template_can_be_loaded_explicitly(self, monkeypatch):
        monkeypatch.delenv("SCHWAB_POLICY_PATH", raising=False)

        policy = load_policy_config(path=DEFAULT_POLICY_TEMPLATE_PATH)

        assert isinstance(policy, PolicyConfig)
        assert policy.source_path is not None
        assert "policy.template.json" in policy.source_path
        assert "acct_inherited_ira_1" in policy.tracked_distribution_accounts()

    def test_env_path_overrides_default(self, monkeypatch, tmp_path):
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "inherited_ira_policies": [
                        {
                            "name": "Test Inherited IRA",
                            "accounts": ["custom_ira"],
                            "bucket_type": "depletion",
                            "distribution_deadline": "2032-12-31",
                            "cash_minimum": 50000,
                        }
                    ],
                    "cash_policies": {"custom_taxable": {"low": 10, "high": 20}},
                    "portfolio_cash_target": {"low": 5, "high": 15},
                    "calendar": {"1": "Do the thing"},
                }
            )
        )
        monkeypatch.setenv("SCHWAB_POLICY_PATH", str(policy_path))

        policy = load_policy_config()

        assert policy.source_path == str(policy_path)
        assert policy.tracked_distribution_accounts() == {"custom_ira"}
        assert policy.cash_policies["custom_taxable"] == (10.0, 20.0)
        assert policy.portfolio_cash_target == (5.0, 15.0)


class TestPolicyEvaluation:
    """Tests for policy evaluation against a custom profile."""

    def test_evaluate_policy_uses_supplied_profile(self):
        policy = PolicyConfig(
            inherited_ira_policies=[],
            cash_policies={"acct_test": (10.0, 20.0)},
            portfolio_cash_target=(5.0, 25.0),
            calendar={1: "January check"},
        )

        delta = evaluate_policy(
            account_balances={"acct_test": {"total_value": 100.0, "cash": 40.0}},
            ytd_distributions={},
            total_cash_pct=30.0,
            today=date(2026, 1, 15),
            policy_config=policy,
        )

        assert any(alert.bucket == "acct_test" for alert in delta.alerts)
        assert any(alert.bucket == "portfolio" for alert in delta.alerts)
        assert delta.calendar_actions == ["January check"]
