from src.core.portfolio_service import (
    analyze_allocation,
    build_account_balances,
    build_portfolio_summary,
    build_positions,
)


def _accounts_fixture():
    return [
        {
            "securitiesAccount": {
                "accountNumber": "1111",
                "currentBalances": {"liquidationValue": 10000, "cashBalance": 1000},
                "positions": [
                    {
                        "instrument": {"symbol": "SWGXX", "assetType": "MUTUAL_FUND"},
                        "marketValue": 2000,
                        "longQuantity": 2000,
                    },
                    {
                        "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                        "marketValue": 3000,
                        "longQuantity": 10,
                        "averagePrice": 250,
                        "unrealizedProfitLoss": 100,
                        "currentDayProfitLoss": 25,
                        "currentDayProfitLossPercentage": 0.8,
                    },
                ],
            }
        },
        {
            "securitiesAccount": {
                "accountNumber": "2222",
                "currentBalances": {"liquidationValue": 5000, "cashBalance": 500},
                "positions": [
                    {
                        "instrument": {"symbol": "MSFT", "assetType": "EQUITY"},
                        "marketValue": 2500,
                        "longQuantity": 5,
                        "averagePrice": 400,
                        "unrealizedProfitLoss": -50,
                        "currentDayProfitLoss": -10,
                        "currentDayProfitLossPercentage": -0.4,
                    }
                ],
            }
        },
    ]


def _account_name(account_number: str) -> str:
    return f"Account (...{account_number[-4:]})"


def test_build_portfolio_summary_counts_cash_and_positions():
    accounts = _accounts_fixture()
    summary = build_portfolio_summary(accounts, _account_name, {"SWGXX"})

    assert summary["total_value"] == 15000
    assert summary["total_cash"] == 3500
    assert summary["total_invested"] == 11500
    assert summary["position_count"] == 2
    assert summary["positions"][0]["symbol"] in {"AAPL", "MSFT"}


def test_build_positions_filters_by_symbol():
    accounts = _accounts_fixture()
    positions = build_positions(accounts, _account_name, symbol="AAPL")

    assert len(positions) == 1
    assert positions[0]["symbol"] == "AAPL"
    assert positions[0]["percentage_of_portfolio"] > 0


def test_build_account_balances_includes_money_market_cash():
    accounts = _accounts_fixture()
    balances = build_account_balances(accounts, _account_name, {"SWGXX"})

    assert balances[0]["cash_balance"] == 3000
    assert balances[1]["cash_balance"] == 500


def test_analyze_allocation_outputs_expected_keys():
    accounts = _accounts_fixture()
    analysis = analyze_allocation(accounts)

    assert "diversification_score" in analysis
    assert "by_asset_type" in analysis
    assert "concentration_risks" in analysis
    assert len(analysis["top_holdings_pct"]) >= 2


