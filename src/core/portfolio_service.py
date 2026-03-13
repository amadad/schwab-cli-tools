"""Shared portfolio aggregation utilities."""

from __future__ import annotations

from collections.abc import Callable

from src.core.models import (
    AccountBalance,
    AccountSnapshot,
    AllocationAnalysis,
    AllocationSlice,
    ConcentrationRisk,
    PortfolioSummary,
    PositionSnapshot,
    TopHolding,
)

AccountNameResolver = Callable[[str], str]


def _position_quantity(position: dict) -> float:
    """Return normalized position quantity.

    Schwab payloads typically use ``longQuantity`` for long positions and
    ``shortQuantity`` for shorts. We normalize shorts to a negative quantity.
    """
    long_quantity = float(position.get("longQuantity", 0) or 0)
    short_quantity = float(position.get("shortQuantity", 0) or 0)
    if long_quantity:
        return long_quantity
    if short_quantity:
        return -short_quantity
    return 0.0


def _build_position_record(
    position: dict,
    *,
    account_number: str,
    account_name: str,
    money_market_symbols: set[str] | frozenset[str],
) -> PositionSnapshot:
    """Build a normalized position record from a Schwab position payload."""
    instrument = position.get("instrument", {})
    symbol = instrument.get("symbol", "")
    quantity = _position_quantity(position)
    average_price = float(position.get("averagePrice", 0) or 0)
    market_value = float(position.get("marketValue", 0) or 0)
    cost_basis = average_price * abs(quantity)

    return PositionSnapshot(
        symbol=symbol,
        description=instrument.get("description"),
        quantity=quantity,
        market_value=market_value,
        average_price=average_price,
        cost_basis=cost_basis,
        unrealized_pl=float(position.get("unrealizedProfitLoss", 0) or 0),
        day_pl=(
            float(position.get("currentDayProfitLoss", 0) or 0)
            if position.get("currentDayProfitLoss") is not None
            else None
        ),
        day_pl_pct=(
            float(position.get("currentDayProfitLossPercentage", 0) or 0)
            if position.get("currentDayProfitLossPercentage") is not None
            else None
        ),
        account=account_name,
        account_number=account_number,
        asset_type=instrument.get("assetType", "UNKNOWN"),
        is_money_market=symbol in money_market_symbols,
    )


def build_portfolio_summary_model(
    accounts: list[dict],
    account_name_resolver: AccountNameResolver,
    money_market_symbols: set[str] | frozenset[str],
) -> PortfolioSummary:
    """Build a typed portfolio summary from account payloads."""
    total_value = 0.0
    total_cash = 0.0
    total_unrealized_pl = 0.0
    all_positions: list[PositionSnapshot] = []

    for account_wrapper in accounts:
        account = account_wrapper.get("securitiesAccount", {})
        balances = account.get("currentBalances", {})
        positions = account.get("positions", [])
        account_number = account.get("accountNumber", "")
        account_name = account_name_resolver(account_number)

        account_value = float(balances.get("liquidationValue", 0) or 0)
        cash = float(balances.get("cashBalance", 0) or 0)

        for raw_position in positions:
            position = _build_position_record(
                raw_position,
                account_number=account_number,
                account_name=account_name,
                money_market_symbols=money_market_symbols,
            )

            if position.is_money_market:
                cash += position.market_value
                continue

            total_unrealized_pl += position.unrealized_pl or 0.0
            all_positions.append(position)

        total_value += account_value
        total_cash += cash

    all_positions.sort(key=lambda position: position.market_value, reverse=True)

    for position in all_positions:
        position.percentage = position.market_value / total_value * 100 if total_value > 0 else 0.0

    return PortfolioSummary(
        total_value=total_value,
        total_cash=total_cash,
        total_invested=total_value - total_cash,
        total_unrealized_pl=total_unrealized_pl,
        cash_percentage=(total_cash / total_value * 100) if total_value > 0 else 0.0,
        account_count=len(accounts),
        position_count=len(all_positions),
        positions=all_positions,
    )


def build_portfolio_summary(
    accounts: list[dict],
    account_name_resolver: AccountNameResolver,
    money_market_symbols: set[str] | frozenset[str],
) -> dict:
    """Build a comprehensive portfolio summary from account payloads."""
    return build_portfolio_summary_model(
        accounts,
        account_name_resolver,
        money_market_symbols,
    ).to_dict(include_positions=True)


def build_positions_model(
    accounts: list[dict],
    account_name_resolver: AccountNameResolver,
    symbol: str | None = None,
    money_market_symbols: set[str] | frozenset[str] = frozenset(),
    include_account_number: bool = False,
) -> list[PositionSnapshot]:
    """Build typed position data across all accounts."""
    positions: list[PositionSnapshot] = []
    total_portfolio_value = 0.0

    for account in accounts:
        sec_account = account.get("securitiesAccount", {})
        balances = sec_account.get("currentBalances", {})
        total_portfolio_value += float(balances.get("liquidationValue", 0) or 0)

    for account in accounts:
        sec_account = account.get("securitiesAccount", {})
        account_number = sec_account.get("accountNumber", "")
        account_name = account_name_resolver(account_number)

        for raw_position in sec_account.get("positions", []):
            position = _build_position_record(
                raw_position,
                account_number=account_number,
                account_name=account_name,
                money_market_symbols=money_market_symbols,
            )

            if symbol and position.symbol.upper() != symbol.upper():
                continue

            if not include_account_number:
                position.account_number = None

            position.percentage_of_portfolio = (
                position.market_value / total_portfolio_value * 100
                if total_portfolio_value > 0
                else 0.0
            )
            positions.append(position)

    positions.sort(key=lambda position: position.market_value, reverse=True)
    return positions


def build_positions(
    accounts: list[dict],
    account_name_resolver: AccountNameResolver,
    symbol: str | None = None,
    money_market_symbols: set[str] | frozenset[str] = frozenset(),
    include_account_number: bool = False,
) -> list[dict]:
    """Build detailed position data across all accounts."""
    return [
        position.to_dict()
        for position in build_positions_model(
            accounts,
            account_name_resolver,
            symbol=symbol,
            money_market_symbols=money_market_symbols,
            include_account_number=include_account_number,
        )
    ]


def build_account_balances_model(
    accounts: list[dict],
    account_name_resolver: AccountNameResolver,
    money_market_symbols: set[str] | frozenset[str],
) -> list[AccountBalance]:
    """Build typed account balance summaries."""
    balances: list[AccountBalance] = []

    for account in accounts:
        sec_account = account.get("securitiesAccount", {})
        account_number = sec_account.get("accountNumber", "")
        account_name = account_name_resolver(account_number)
        current_balances = sec_account.get("currentBalances", {})
        positions = sec_account.get("positions", [])

        total_value = float(current_balances.get("liquidationValue", 0) or 0)
        cash_balance = float(current_balances.get("cashBalance", 0) or 0)

        money_market_cash = 0.0
        for raw_position in positions:
            position = _build_position_record(
                raw_position,
                account_number=account_number,
                account_name=account_name,
                money_market_symbols=money_market_symbols,
            )
            if position.is_money_market:
                money_market_cash += position.market_value

        total_cash = cash_balance + money_market_cash

        balances.append(
            AccountBalance(
                account=account_name,
                account_name=account_name,
                account_type=sec_account.get("type", "Unknown"),
                total_value=total_value,
                cash_balance=total_cash,
                money_market_value=money_market_cash,
                buying_power=float(current_balances.get("buyingPower", 0) or 0),
                invested_amount=total_value - total_cash,
            )
        )

    balances.sort(key=lambda balance: balance.total_value, reverse=True)
    return balances


def build_account_balances(
    accounts: list[dict],
    account_name_resolver: AccountNameResolver,
    money_market_symbols: set[str] | frozenset[str],
) -> list[dict]:
    """Build account balance summaries."""
    return [
        balance.to_dict()
        for balance in build_account_balances_model(
            accounts,
            account_name_resolver,
            money_market_symbols,
        )
    ]


def build_account_snapshots_model(
    accounts: list[dict],
    account_name_resolver: AccountNameResolver,
    money_market_symbols: set[str] | frozenset[str],
) -> list[AccountSnapshot]:
    """Build typed account snapshots, including underlying positions."""
    snapshots: list[AccountSnapshot] = []

    for account in accounts:
        sec_account = account.get("securitiesAccount", {})
        account_number = sec_account.get("accountNumber", "")
        account_name = account_name_resolver(account_number)
        current_balances = sec_account.get("currentBalances", {})
        total_value = float(current_balances.get("liquidationValue", 0) or 0)
        cash_balance = float(current_balances.get("cashBalance", 0) or 0)
        buying_power = float(current_balances.get("buyingPower", 0) or 0)

        positions: list[PositionSnapshot] = []
        money_market_value = 0.0

        for raw_position in sec_account.get("positions", []):
            position = _build_position_record(
                raw_position,
                account_number=account_number,
                account_name=account_name,
                money_market_symbols=money_market_symbols,
            )
            positions.append(position)
            if position.is_money_market:
                money_market_value += position.market_value

        positions.sort(key=lambda position: position.market_value, reverse=True)
        total_cash = cash_balance + money_market_value

        snapshots.append(
            AccountSnapshot(
                account=account_name,
                account_number=account_number,
                account_type=sec_account.get("type", "Unknown"),
                total_value=total_value,
                cash_balance=cash_balance,
                money_market_value=money_market_value,
                total_cash=total_cash,
                invested_value=total_value - total_cash,
                buying_power=buying_power,
                position_count=sum(1 for position in positions if not position.is_money_market),
                positions=positions,
            )
        )

    snapshots.sort(key=lambda snapshot: snapshot.total_value, reverse=True)
    return snapshots


def build_account_snapshots(
    accounts: list[dict],
    account_name_resolver: AccountNameResolver,
    money_market_symbols: set[str] | frozenset[str],
) -> list[dict]:
    """Build normalized account snapshots, including underlying positions."""
    return [
        snapshot.to_dict()
        for snapshot in build_account_snapshots_model(
            accounts,
            account_name_resolver,
            money_market_symbols,
        )
    ]


def analyze_allocation_model(accounts: list[dict]) -> AllocationAnalysis:
    """Analyze portfolio allocation and concentration risks."""
    total_value = 0.0
    symbol_values: dict[str, float] = {}
    type_values: dict[str, float] = {}

    for account in accounts:
        sec_account = account.get("securitiesAccount", {})

        for position in sec_account.get("positions", []):
            instrument = position.get("instrument", {})
            symbol = instrument.get("symbol", "Unknown")
            asset_type = instrument.get("assetType", "Unknown")
            value = float(position.get("marketValue", 0) or 0)

            total_value += value
            symbol_values[symbol] = symbol_values.get(symbol, 0.0) + value
            type_values[asset_type] = type_values.get(asset_type, 0.0) + value

    by_asset_type = {
        asset_type: AllocationSlice(
            value=value,
            percentage=(value / total_value * 100) if total_value > 0 else 0.0,
        )
        for asset_type, value in type_values.items()
    }

    concentration_risks: list[ConcentrationRisk] = []
    top_holdings_pct: list[TopHolding] = []

    for symbol, value in symbol_values.items():
        percentage = (value / total_value * 100) if total_value > 0 else 0.0

        top_holdings_pct.append(
            TopHolding(symbol=symbol, percentage=round(percentage, 2), value=value)
        )

        if percentage > 10:
            concentration_risks.append(
                ConcentrationRisk(
                    symbol=symbol,
                    percentage=round(percentage, 2),
                    value=value,
                    risk_level="High" if percentage > 20 else "Medium",
                )
            )

    top_holdings_pct.sort(key=lambda holding: holding.percentage, reverse=True)
    top_holdings_pct = top_holdings_pct[:15]

    hhi = (
        sum((value / total_value) ** 2 for value in symbol_values.values())
        if total_value > 0
        else 0.0
    )
    diversification_score = round((1 - hhi) * 100, 2)

    return AllocationAnalysis(
        diversification_score=diversification_score,
        by_asset_type=by_asset_type,
        concentration_risks=concentration_risks,
        top_holdings_pct=top_holdings_pct,
    )


def analyze_allocation(accounts: list[dict]) -> dict:
    """Analyze portfolio allocation and concentration risks."""
    return analyze_allocation_model(accounts).to_dict()
