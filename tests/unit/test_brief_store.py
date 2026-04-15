from pathlib import Path

from src.schwab_client.history import HistoryStore


def _canonical_snapshot(total_value: float = 250000.0) -> dict:
    return {
        "generated_at": "2026-03-13T08:00:00",
        "portfolio": {
            "summary": {
                "total_value": total_value,
                "api_value": total_value,
                "manual_value": 0.0,
                "total_cash": 60000.0,
                "manual_cash": 0.0,
                "total_invested": total_value - 60000.0,
                "total_unrealized_pl": 12000.0,
                "cash_percentage": round(60000.0 / total_value * 100, 1),
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
                    "cash_balance": 60000.0,
                    "money_market_value": 0.0,
                    "total_cash": 60000.0,
                    "invested_value": total_value - 60000.0,
                    "buying_power": 0.0,
                    "position_count": 1,
                    "positions": [
                        {
                            "symbol": "AAPL",
                            "asset_type": "EQUITY",
                            "quantity": 10.0,
                            "market_value": total_value - 60000.0,
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
            "allocation": {"diversification_score": 88.0, "by_asset_type": {}, "concentration_risks": [], "top_holdings_pct": []},
        },
        "market": {"vix": {"vix": 17.2, "signal": "normal"}, "signals": None, "indices": None, "sectors": None},
        "errors": [],
    }


def test_brief_run_round_trip_and_delivery_logging(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.db")
    snapshot_meta = store.store_snapshot(_canonical_snapshot(), source_command="snapshot")

    run_id = store.create_or_update_brief_run(
        snapshot_id=snapshot_meta["snapshot_id"],
        snapshot_observed_at="2026-03-13T08:00:00",
        brief_for_date="2026-03-13",
        status="ready",
        context_json={"summary": {"cash_percentage": 24.0}},
        scorecard_json={"alerts": []},
        analysis_json={"summary": "All clear."},
        briefing_json={"bottom_line": "All clear."},
        email_subject="Brief • Mar 13 • All clear",
        email_html="<p>hi</p>",
        email_text="hi",
    )
    delivery_id = store.record_brief_delivery(
        run_id,
        channel="email",
        recipient_json={"to": ["test@example.com"]},
        provider="resend",
        provider_message_id="msg_123",
        dry_run=False,
        status="sent",
        error_text=None,
    )

    run = store.get_brief_run(run_id)
    assert run is not None
    assert run["snapshot_id"] == snapshot_meta["snapshot_id"]
    assert run["context_json"]["summary"]["cash_percentage"] == 24.0
    assert run["briefing_json"]["bottom_line"] == "All clear."
    assert run["deliveries"][0]["id"] == delivery_id
    assert run["deliveries"][0]["recipient_json"]["to"] == ["test@example.com"]

    latest = store.find_latest_brief_for_date("2026-03-13")
    assert latest is not None
    assert latest["id"] == run_id


def test_brief_run_update_preserves_unspecified_json_fields(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.db")
    snapshot_meta = store.store_snapshot(_canonical_snapshot(), source_command="snapshot")

    run_id = store.create_or_update_brief_run(
        snapshot_id=snapshot_meta["snapshot_id"],
        snapshot_observed_at="2026-03-13T08:00:00",
        brief_for_date="2026-03-13",
        status="ready",
        context_json={"summary": {"cash_percentage": 24.0}},
        scorecard_json={"alerts": [{"bucket": "Trading"}]},
    )
    store.create_or_update_brief_run(
        snapshot_id=snapshot_meta["snapshot_id"],
        snapshot_observed_at="2026-03-13T08:00:00",
        brief_for_date="2026-03-13",
        status="sent",
        sent_at="2026-03-13T08:30:00",
    )

    run = store.get_brief_run(run_id)
    assert run is not None
    assert run["status"] == "sent"
    assert run["sent_at"] == "2026-03-13T08:30:00"
    assert run["context_json"]["summary"]["cash_percentage"] == 24.0
    assert run["scorecard_json"]["alerts"][0]["bucket"] == "Trading"
