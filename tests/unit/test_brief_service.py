from pathlib import Path

from src.core.brief_service import BriefService
from src.schwab_client.history import HistoryStore


def _snapshot() -> dict:
    return {
        "generated_at": "2026-03-13T08:00:00",
        "portfolio": {
            "summary": {
                "total_value": 250000.0,
                "api_value": 250000.0,
                "manual_value": 0.0,
                "total_cash": 60000.0,
                "manual_cash": 0.0,
                "total_invested": 190000.0,
                "total_unrealized_pl": 12000.0,
                "cash_percentage": 24.0,
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
                    "total_value": 250000.0,
                    "cash_balance": 60000.0,
                    "money_market_value": 0.0,
                    "total_cash": 60000.0,
                    "invested_value": 190000.0,
                    "buying_power": 0.0,
                    "position_count": 1,
                    "positions": [],
                }
            ],
            "manual_accounts": {"source_path": None, "last_updated": None, "summary": {}, "accounts": []},
            "positions": [],
            "allocation": {"diversification_score": 90.0, "by_asset_type": {}, "concentration_risks": [], "top_holdings_pct": []},
        },
        "market": {"vix": {"vix": 17.2, "signal": "normal"}, "signals": None, "indices": None, "sectors": None},
        "errors": [],
    }


def test_send_records_delivery_and_marks_run_sent(tmp_path: Path, monkeypatch):
    history = HistoryStore(tmp_path / "history.db")
    snapshot_meta = history.store_snapshot(_snapshot(), source_command="snapshot")
    run_id = history.create_or_update_brief_run(
        snapshot_id=snapshot_meta["snapshot_id"],
        snapshot_observed_at="2026-03-13T08:00:00",
        brief_for_date="2026-03-13",
        status="ready",
        briefing_json={"bottom_line": "All clear."},
        email_subject="Brief • Mar 13 • All clear",
        email_html="<p>Hello</p>",
        email_text="Hello",
    )
    monkeypatch.setattr("src.core.brief_service.send_email", lambda subject, html, text: {"id": "email_123"})

    service = BriefService(history_store=history, repo_root=tmp_path)
    result = service.send(run_id=run_id, force=True)
    run = history.get_brief_run(run_id)

    assert result["status"] == "sent"
    assert run is not None
    assert run["status"] == "sent"
    assert run["deliveries"][0]["provider_message_id"] == "email_123"


def test_send_skips_already_sent_without_force(tmp_path: Path):
    history = HistoryStore(tmp_path / "history.db")
    snapshot_meta = history.store_snapshot(_snapshot(), source_command="snapshot")
    run_id = history.create_or_update_brief_run(
        snapshot_id=snapshot_meta["snapshot_id"],
        snapshot_observed_at="2026-03-13T08:00:00",
        brief_for_date="2026-03-13",
        status="sent",
        email_subject="Brief • Mar 13 • All clear",
        email_html="<p>Hello</p>",
        email_text="Hello",
        sent_at="2026-03-13T08:30:00",
    )

    service = BriefService(history_store=history, repo_root=tmp_path)
    result = service.send(run_id=run_id)

    assert result["status"] == "skipped"
    assert result["reason"] == "already_sent"
