"""Tests for SQLite-backed snapshot history."""

import json
from pathlib import Path

from src.schwab_client.history import HistoryStore


def _canonical_snapshot() -> dict:
    return {
        "generated_at": "2026-03-13T08:00:00",
        "portfolio": {
            "summary": {
                "total_value": 250000.0,
                "api_value": 200000.0,
                "manual_value": 50000.0,
                "total_cash": 60000.0,
                "manual_cash": 10000.0,
                "total_invested": 190000.0,
                "total_unrealized_pl": 12000.0,
                "cash_percentage": 24.0,
                "account_count": 3,
                "api_account_count": 2,
                "manual_account_count": 1,
                "position_count": 2,
            },
            "api_accounts": [
                {
                    "account": "Trading (...2140)",
                    "account_alias": "acct_trading",
                    "account_number_last4": "2140",
                    "account_type": "Individual",
                    "total_value": 200000.0,
                    "cash_balance": 50000.0,
                    "money_market_value": 0.0,
                    "total_cash": 50000.0,
                    "invested_value": 150000.0,
                    "buying_power": 0.0,
                    "position_count": 2,
                    "positions": [
                        {
                            "symbol": "AAPL",
                            "asset_type": "EQUITY",
                            "quantity": 100.0,
                            "market_value": 100000.0,
                            "average_price": 850.0,
                            "cost_basis": 85000.0,
                            "unrealized_pl": 15000.0,
                            "percentage": 40.0,
                            "is_money_market": False,
                        },
                        {
                            "symbol": "MSFT",
                            "asset_type": "EQUITY",
                            "quantity": 50.0,
                            "market_value": 50000.0,
                            "average_price": 760.0,
                            "cost_basis": 38000.0,
                            "unrealized_pl": 12000.0,
                            "percentage": 20.0,
                            "is_money_market": False,
                        },
                    ],
                }
            ],
            "manual_accounts": {
                "source_path": "/tmp/manual_accounts.json",
                "last_updated": "2026-03-10",
                "summary": {
                    "total_value": 50000.0,
                    "total_cash": 10000.0,
                    "total_invested": 40000.0,
                    "account_count": 1,
                    "by_category": {"cash": 10000.0, "education": 40000.0},
                },
                "accounts": [
                    {
                        "id": "manual_cash",
                        "name": "Household Cash",
                        "last_four": "cash",
                        "type": "bank",
                        "category": "cash",
                        "provider": "Bank",
                        "tax_status": "taxable",
                        "value": 10000.0,
                    }
                ],
            },
            "positions": [
                {
                    "symbol": "AAPL",
                    "asset_type": "EQUITY",
                    "account": "Trading (...2140)",
                    "account_alias": "acct_trading",
                    "account_number_last4": "2140",
                    "quantity": 100.0,
                    "market_value": 100000.0,
                    "average_price": 850.0,
                    "cost_basis": 85000.0,
                    "unrealized_pl": 15000.0,
                    "percentage_of_portfolio": 40.0,
                    "is_money_market": False,
                }
            ],
            "allocation": {
                "diversification_score": 88.0,
                "by_asset_type": {"EQUITY": {"value": 150000.0, "percentage": 75.0}},
                "concentration_risks": [],
                "top_holdings_pct": [{"symbol": "AAPL", "percentage": 40.0, "value": 100000.0}],
            },
        },
        "market": {
            "signals": {
                "signals": {
                    "market_sentiment": "risk_on",
                    "sector_rotation": "risk_on",
                },
                "overall": "favorable",
                "recommendation": "Stay invested",
            },
            "vix": {"vix": 17.2, "signal": "normal"},
            "indices": {
                "indices": {
                    "$SPX": {
                        "name": "S&P 500",
                        "price": 5400.0,
                        "change": 55.0,
                        "change_pct": 1.03,
                    }
                }
            },
            "sectors": {
                "sectors": [
                    {
                        "symbol": "XLK",
                        "sector": "Technology",
                        "price": 210.0,
                        "change_pct": 1.4,
                    }
                ]
            },
        },
    }


def test_history_store_persists_and_queries_snapshot(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.db")
    result = store.store_snapshot(_canonical_snapshot(), source_command="snapshot")

    assert result["snapshot_id"] > 0
    runs = store.list_runs(limit=5)
    assert len(runs) == 1
    assert runs[0]["total_value"] == 250000.0
    assert runs[0]["manual_value"] == 50000.0

    positions = store.get_position_history(symbol="AAPL", limit=5)
    assert len(positions) == 1
    assert positions[0]["account_alias"] == "acct_trading"
    assert positions[0]["market_value"] == 100000.0

    market = store.get_market_history(limit=5)
    assert len(market) == 1
    assert market[0]["overall"] == "favorable"
    assert market[0]["vix_value"] == 17.2

    rows = store.execute_query(
        "SELECT symbol, market_value FROM position_history WHERE symbol = 'AAPL'"
    )
    assert rows == [{"symbol": "AAPL", "market_value": 100000.0}]


def test_history_store_imports_legacy_snapshot_json(tmp_path: Path):
    legacy_snapshot = {
        "timestamp": "2026-01-19T07:40:31.952703",
        "date": "2026-01-19",
        "summary": {
            "total_value": 180000.0,
            "api_value": 150000.0,
            "manual_value": 30000.0,
            "total_cash": 45000.0,
            "total_invested": 135000.0,
            "api_account_count": 2,
            "manual_account_count": 1,
            "position_count": 1,
        },
        "api_accounts": [
            {
                "account_number_last4": "9999",
                "account_type": "CASH",
                "liquidation_value": 150000.0,
                "cash_balance": 50000.0,
                "money_market_value": 10000.0,
                "total_cash": 60000.0,
                "invested_value": 90000.0,
                "position_count": 1,
                "positions": [
                    {
                        "symbol": "AAPL",
                        "quantity": 2.0,
                        "market_value": 500.0,
                        "cost_basis": 320.0,
                        "unrealized_pnl": 180.0,
                        "asset_type": "EQUITY",
                        "is_money_market": False,
                    }
                ],
            }
        ],
        "manual_accounts": [
            {
                "id": "manual_cash",
                "name": "Cash Reserve",
                "last_four": "cash",
                "type": "bank",
                "category": "cash",
                "provider": "Local Bank",
                "tax_status": "taxable",
                "value": 30000.0,
            }
        ],
    }

    json_path = tmp_path / "legacy_snapshot.json"
    json_path.write_text(json.dumps(legacy_snapshot, indent=2))

    store = HistoryStore(tmp_path / "history.db")
    result = store.import_json_paths([str(json_path)])

    assert result["imported"] == 1

    portfolio_history = store.get_portfolio_history(limit=5)
    assert len(portfolio_history) == 1
    assert portfolio_history[0]["api_value"] == 150000.0
    assert portfolio_history[0]["manual_value"] == 30000.0

    positions = store.get_position_history(symbol="AAPL", limit=5)
    assert len(positions) == 1
    assert positions[0]["market_value"] == 500.0
