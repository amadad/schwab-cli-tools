import io
import json
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from src.core.context import PortfolioContext
from src.core.models import AccountSnapshot, PortfolioSummary
from src.core.policy import PolicyDelta
from src.schwab_client.cli.commands.context_cmd import cmd_context


def _summary(*, cash_percentage: float = 20.0) -> PortfolioSummary:
    return PortfolioSummary(
        total_value=100.0,
        total_cash=cash_percentage,
        total_invested=100.0 - cash_percentage,
        total_unrealized_pl=0.0,
        cash_percentage=cash_percentage,
        account_count=1,
        position_count=0,
    )


@patch("src.core.context.evaluate_policy")
def test_context_policy_uses_account_alias(mock_evaluate_policy):
    captured: dict[str, object] = {}

    def fake_evaluate_policy(*, account_balances, ytd_distributions, total_cash_pct):
        captured["account_balances"] = account_balances
        captured["ytd_distributions"] = ytd_distributions
        captured["total_cash_pct"] = total_cash_pct
        return PolicyDelta()

    mock_evaluate_policy.side_effect = fake_evaluate_policy

    ctx = PortfolioContext(
        summary=_summary(),
        accounts=[
            AccountSnapshot(
                account="Mom IRA (...8652)",
                account_alias="mom_ira",
                account_number="12345678",
                total_value=100.0,
                total_cash=20.0,
            )
        ],
    )

    ctx._evaluate_policy()

    assert captured["account_balances"] == {
        "mom_ira": {"total_value": 100.0, "cash": 20.0}
    }
    assert captured["total_cash_pct"] == 20.0


@patch("src.schwab_client.cli.commands.context_cmd.PortfolioContext")
@patch("src.schwab_client.cli.commands.context_cmd.get_client")
@patch("src.schwab_client.cli.commands.context_cmd.get_cached_market_client")
def test_cmd_context_surfaces_market_auth_failure_in_json(
    mock_get_market_client,
    mock_get_client,
    mock_context_cls,
):
    mock_get_client.return_value = MagicMock()
    mock_get_market_client.side_effect = RuntimeError("market auth unavailable")

    ctx = PortfolioContext(summary=_summary(), errors=[])
    mock_context_cls.assemble.return_value = ctx

    output = io.StringIO()
    with redirect_stdout(output):
        cmd_context(output_mode="json")

    payload = json.loads(output.getvalue())
    assert payload["success"] is True
    assert payload["data"]["market_available"] is False
    assert payload["data"]["errors"] == ["market_auth: market auth unavailable"]
