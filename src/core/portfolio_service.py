"""Shared portfolio aggregation utilities."""

from collections.abc import Callable
from typing import Any

AccountNameResolver = Callable[[str], str]


def build_portfolio_summary(
    accounts: list[dict[str, Any]],
    account_name_resolver: AccountNameResolver,
    money_market_symbols: set[str] | frozenset[str],
) -> dict[str, Any]:
    """Build a comprehensive portfolio summary from account payloads."""
    total_value = 0.0
    total_cash = 0.0
    all_positions: list[dict[str, Any]] = []

    for account_wrapper in accounts:
        account = account_wrapper.get("securitiesAccount", {})
        balances = account.get("currentBalances", {})
        positions = account.get("positions", [])
        account_number = account.get("accountNumber", "")

        acc_value = balances.get("liquidationValue", 0)
        cash = balances.get("cashBalance", 0)

        for pos in positions:
            instrument = pos.get("instrument", {})
            symbol = instrument.get("symbol", "")
            market_value = pos.get("marketValue", 0)

            if symbol in money_market_symbols:
                cash += market_value
            else:
                all_positions.append(
                    {
                        "symbol": symbol,
                        "quantity": pos.get("longQuantity", 0),
                        "market_value": market_value,
                        "average_price": pos.get("averagePrice", 0),
                        "unrealized_pl": pos.get("unrealizedProfitLoss", 0),
                        "unrealized_pl_pct": pos.get("unrealizedProfitLossPercentage", 0),
                        "day_pl": pos.get("currentDayProfitLoss", 0),
                        "day_pl_pct": pos.get("currentDayProfitLossPercentage", 0),
                        "account": account_name_resolver(account_number),
                        "account_number": account_number,
                        "asset_type": instrument.get("assetType", "UNKNOWN"),
                    }
                )

        total_value += acc_value
        total_cash += cash

    all_positions.sort(key=lambda x: x["market_value"], reverse=True)

    total_unrealized_pl = sum(pos.get("unrealized_pl", 0) for pos in all_positions)

    for pos in all_positions:
        pos["percentage"] = pos["market_value"] / total_value * 100 if total_value > 0 else 0

    return {
        "total_value": total_value,
        "total_cash": total_cash,
        "total_invested": total_value - total_cash,
        "total_unrealized_pl": total_unrealized_pl,
        "cash_percentage": (total_cash / total_value * 100) if total_value > 0 else 0,
        "account_count": len(accounts),
        "position_count": len(all_positions),
        "positions": all_positions,
    }


def build_positions(
    accounts: list[dict[str, Any]],
    account_name_resolver: AccountNameResolver,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    """Build detailed position data across accounts."""
    positions: list[dict[str, Any]] = []
    total_portfolio_value = 0.0

    for account in accounts:
        sec_account = account.get("securitiesAccount", {})
        balances = sec_account.get("currentBalances", {})
        total_portfolio_value += balances.get("liquidationValue", 0)

    for account in accounts:
        sec_account = account.get("securitiesAccount", {})
        acc_num = sec_account.get("accountNumber", "")

        for pos in sec_account.get("positions", []):
            instrument = pos.get("instrument", {})
            pos_symbol = instrument.get("symbol", "")

            if symbol and pos_symbol.upper() != symbol.upper():
                continue

            quantity = pos.get("longQuantity", 0)
            market_value = pos.get("marketValue", 0)
            avg_price = pos.get("averagePrice", 0)

            positions.append(
                {
                    "symbol": pos_symbol,
                    "account": account_name_resolver(acc_num),
                    "quantity": quantity,
                    "market_value": market_value,
                    "cost_basis": avg_price * quantity,
                    "unrealized_pl": pos.get("unrealizedProfitLoss", 0),
                    "day_change": pos.get("currentDayProfitLoss", 0),
                    "percentage_of_portfolio": (
                        (market_value / total_portfolio_value * 100)
                        if total_portfolio_value > 0
                        else 0
                    ),
                }
            )

    positions.sort(key=lambda x: x["market_value"], reverse=True)
    return positions


def build_account_balances(
    accounts: list[dict[str, Any]],
    account_name_resolver: AccountNameResolver,
    money_market_symbols: set[str] | frozenset[str],
) -> list[dict[str, Any]]:
    """Build account balance summaries."""
    balances: list[dict[str, Any]] = []

    for account in accounts:
        sec_account = account.get("securitiesAccount", {})
        acc_num = sec_account.get("accountNumber", "")
        current_balances = sec_account.get("currentBalances", {})
        positions = sec_account.get("positions", [])

        total_value = current_balances.get("liquidationValue", 0)
        cash_balance = current_balances.get("cashBalance", 0)

        money_market_cash = 0
        for pos in positions:
            instrument = pos.get("instrument", {})
            symbol = instrument.get("symbol", "")
            if symbol in money_market_symbols:
                money_market_cash += pos.get("marketValue", 0)

        total_cash = cash_balance + money_market_cash

        balances.append(
            {
                "account": account_name_resolver(acc_num),
                "account_type": sec_account.get("type", "Unknown"),
                "total_value": total_value,
                "cash_balance": total_cash,
                "buying_power": current_balances.get("buyingPower", 0),
                "invested_amount": total_value - total_cash,
            }
        )

    return balances


def analyze_allocation(
    accounts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze portfolio allocation and concentration risks."""
    total_value = 0.0
    symbol_values: dict[str, float] = {}
    type_values: dict[str, float] = {}

    for account in accounts:
        sec_account = account.get("securitiesAccount", {})

        for pos in sec_account.get("positions", []):
            instrument = pos.get("instrument", {})
            symbol = instrument.get("symbol", "Unknown")
            asset_type = instrument.get("assetType", "Unknown")
            value = pos.get("marketValue", 0)

            total_value += value

            symbol_values[symbol] = symbol_values.get(symbol, 0) + value
            type_values[asset_type] = type_values.get(asset_type, 0) + value

    by_asset_type = {}
    for asset_type, value in type_values.items():
        by_asset_type[asset_type] = {
            "value": value,
            "percentage": (value / total_value * 100) if total_value > 0 else 0,
        }

    concentration_risks = []
    top_holdings_pct = []

    for symbol, value in symbol_values.items():
        pct = (value / total_value * 100) if total_value > 0 else 0

        top_holdings_pct.append({"symbol": symbol, "percentage": round(pct, 2), "value": value})

        if pct > 10:
            concentration_risks.append(
                {
                    "symbol": symbol,
                    "percentage": round(pct, 2),
                    "value": value,
                    "risk_level": "High" if pct > 20 else "Medium",
                }
            )

    top_holdings_pct.sort(key=lambda x: x["percentage"], reverse=True)
    top_holdings_pct = top_holdings_pct[:15]

    hhi = sum((v / total_value) ** 2 for v in symbol_values.values()) if total_value > 0 else 0
    diversification_score = round((1 - hhi) * 100, 2)

    return {
        "diversification_score": diversification_score,
        "by_asset_type": by_asset_type,
        "concentration_risks": concentration_risks,
        "top_holdings_pct": top_holdings_pct,
    }


def build_performance_report(
    accounts: list[dict[str, Any]],
    money_market_symbols: set[str] | frozenset[str],
) -> dict[str, Any]:
    """Build portfolio performance metrics."""
    total_day_pl = 0.0
    total_unrealized_pl = 0.0
    total_value = 0.0
    position_performance: list[dict[str, Any]] = []

    for account in accounts:
        sec_account = account.get("securitiesAccount", {})
        balances = sec_account.get("currentBalances", {})
        total_value += balances.get("liquidationValue", 0)

        for pos in sec_account.get("positions", []):
            instrument = pos.get("instrument", {})
            symbol = instrument.get("symbol", "Unknown")

            day_pl = pos.get("currentDayProfitLoss", 0)
            unrealized_pl = pos.get("unrealizedProfitLoss", 0)

            total_day_pl += day_pl
            total_unrealized_pl += unrealized_pl

            if symbol != "Unknown" and symbol not in money_market_symbols:
                position_performance.append(
                    {
                        "symbol": symbol,
                        "day_pl": day_pl,
                        "day_pl_pct": pos.get("currentDayProfitLossPercentage", 0),
                        "unrealized_pl": unrealized_pl,
                        "market_value": pos.get("marketValue", 0),
                    }
                )

    position_performance.sort(key=lambda x: x["day_pl"], reverse=True)

    winners = [p for p in position_performance if p["day_pl"] > 0][:5]
    losers = [p for p in position_performance if p["day_pl"] < 0]
    losers.sort(key=lambda x: x["day_pl"])
    losers = losers[:5]

    yesterday_value = total_value - total_day_pl
    daily_change_pct = (total_day_pl / yesterday_value * 100) if yesterday_value > 0 else 0

    return {
        "daily_change": total_day_pl,
        "daily_change_pct": daily_change_pct,
        "total_unrealized_pl": total_unrealized_pl,
        "winners": winners,
        "losers": losers,
    }
