from pathlib import Path

from src.core.brief_scorecard import compute
from src.schwab_client.history import HistoryStore


def _snapshot(*, observed_at: str, total_value: float, total_cash: float) -> dict:
    return {
        "generated_at": observed_at,
        "portfolio": {
            "summary": {
                "total_value": total_value,
                "api_value": total_value,
                "manual_value": 0.0,
                "total_cash": total_cash,
                "manual_cash": 0.0,
                "total_invested": total_value - total_cash,
                "total_unrealized_pl": 0.0,
                "cash_percentage": round(total_cash / total_value * 100, 1),
                "account_count": 1,
                "api_account_count": 1,
                "manual_account_count": 0,
                "position_count": 1,
            },
            "api_accounts": [
                {
                    "account": "Trading (...2140)",
                    "account_alias": "ali_trading",
                    "account_number_last4": "2140",
                    "account_type": "Individual",
                    "total_value": total_value,
                    "cash_balance": total_cash,
                    "money_market_value": 0.0,
                    "total_cash": total_cash,
                    "invested_value": total_value - total_cash,
                    "buying_power": 0.0,
                    "position_count": 1,
                    "positions": [
                        {
                            "symbol": "AAPL",
                            "asset_type": "EQUITY",
                            "quantity": 10.0,
                            "market_value": total_value - total_cash,
                            "average_price": 100.0,
                            "cost_basis": 900.0,
                            "unrealized_pl": 100.0,
                            "percentage": 40.0,
                            "is_money_market": False,
                        }
                    ],
                }
            ],
            "manual_accounts": {"source_path": None, "last_updated": None, "summary": {}, "accounts": []},
            "positions": [],
            "allocation": {"diversification_score": 90.0, "by_asset_type": {}, "concentration_risks": [], "top_holdings_pct": []},
        },
        "market": None,
        "errors": [],
    }


def test_scorecard_respects_explicit_snapshot_id(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.db")
    early = store.store_snapshot(
        _snapshot(observed_at="2026-03-10T08:00:00", total_value=1000.0, total_cash=100.0),
        source_command="snapshot",
    )
    later = store.store_snapshot(
        _snapshot(observed_at="2026-03-11T08:00:00", total_value=2000.0, total_cash=800.0),
        source_command="snapshot",
    )

    first_scorecard = compute(store.path, snapshot_id=early["snapshot_id"])
    second_scorecard = compute(store.path, snapshot_id=later["snapshot_id"])

    assert first_scorecard["total_portfolio_value"] == 1000
    assert second_scorecard["total_portfolio_value"] == 2000
    assert first_scorecard["buckets"][0]["value"] == 1000
    assert second_scorecard["buckets"][0]["value"] == 2000
