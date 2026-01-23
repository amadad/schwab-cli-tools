"""
Portfolio commands: portfolio, positions, balance, allocation, performance.
"""

from typing import Any

from config.secure_account_config import secure_config

from ..context import get_client
from ..output import (
    format_currency,
    format_header,
    format_percent,
    handle_cli_error,
    print_json_response,
)


def get_account_display_name(account_number: str) -> str:
    """Get friendly display name for account (centralized)."""
    label = secure_config.get_account_label(account_number)
    if label:
        return label
    if len(account_number) > 4:
        return f"Account (...{account_number[-4:]})"
    return f"Account ({account_number})"


def sanitize_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sanitize positions by masking account numbers."""
    sanitized = []
    for pos in positions:
        entry = dict(pos)
        account_number = entry.pop("account_number", None)
        if account_number:
            entry["account_name"] = get_account_display_name(str(account_number))
            entry["account_number_last4"] = str(account_number)[-4:]
        sanitized.append(entry)
    return sanitized


def cmd_portfolio(
    *,
    output_mode: str = "text",
    include_positions: bool = False,
) -> None:
    """Show portfolio summary."""
    command = "portfolio"
    try:
        client = get_client()
        summary = client.get_portfolio_summary()

        # Sanitize positions
        summary["positions"] = sanitize_positions(summary.get("positions", []))

        if output_mode == "json":
            print_json_response(command, data=summary)
            return

        # Text output
        print(format_header("PORTFOLIO SUMMARY"))
        print(f"  Total Value:      {format_currency(summary.get('total_value'))}")
        print(f"  Total Cash:       {format_currency(summary.get('total_cash'))}")
        print(f"  Total Invested:   {format_currency(summary.get('total_invested'))}")
        print(f"  Cash %:           {format_percent(summary.get('cash_percentage'))}")
        print(f"  Accounts:         {summary.get('account_count', 0)}")
        print(f"  Positions:        {summary.get('position_count', 0)}")

        if include_positions and summary.get("positions"):
            print(format_header("POSITIONS"))
            positions = sorted(
                summary["positions"],
                key=lambda p: p.get("market_value", 0),
                reverse=True,
            )
            for pos in positions[:20]:
                symbol = pos.get("symbol", "???")
                qty = pos.get("quantity", 0)
                value = pos.get("market_value", 0)
                gain = pos.get("day_gain_percent", 0)
                sign = "+" if gain >= 0 else ""
                print(f"  {symbol:8s} {qty:>8.2f} {format_currency(value):>14s}  {sign}{gain:.2f}%")

            if len(summary["positions"]) > 20:
                print(f"  ... and {len(summary['positions']) - 20} more")

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_positions(
    *,
    output_mode: str = "text",
    symbol: str | None = None,
) -> None:
    """Show detailed positions."""
    command = "positions"
    try:
        client = get_client()
        positions = client.get_positions(symbol)

        if output_mode == "json":
            print_json_response(command, data={"positions": positions})
            return

        title = f"POSITIONS - {symbol}" if symbol else "ALL POSITIONS"
        print(format_header(title))

        if not positions:
            print("  No positions found.")
        else:
            # Sort by market value
            positions = sorted(
                positions,
                key=lambda p: p.get("market_value", 0),
                reverse=True,
            )
            for pos in positions:
                sym = pos.get("symbol", "???")
                qty = pos.get("quantity", 0)
                value = pos.get("market_value", 0)
                avg_cost = pos.get("average_cost", 0)
                current = pos.get("current_price", 0)
                gain_pct = pos.get("gain_percent", 0)
                account = pos.get("account_name", "")

                sign = "+" if gain_pct >= 0 else ""
                print(
                    f"  {sym:8s} {qty:>8.2f} @ ${current:>8.2f}  "
                    f"{format_currency(value):>12s}  {sign}{gain_pct:.2f}%  [{account}]"
                )

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_balance(*, output_mode: str = "text") -> None:
    """Show account balances."""
    command = "balance"
    try:
        client = get_client()
        balances = client.get_account_balances()

        if output_mode == "json":
            print_json_response(command, data={"balances": balances})
            return

        print(format_header("ACCOUNT BALANCES"))

        total_value = 0
        total_cash = 0

        for bal in balances:
            name = bal.get("account_name", "Unknown")
            value = bal.get("total_value", 0)
            cash = bal.get("cash_balance", 0)
            total_value += value
            total_cash += cash

            print(f"\n  {name}")
            print(f"    Total:  {format_currency(value)}")
            print(f"    Cash:   {format_currency(cash)}")

        if len(balances) > 1:
            print(f"\n  {'=' * 40}")
            print(f"  TOTAL:    {format_currency(total_value)}")
            print(f"  Cash:     {format_currency(total_cash)}")

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_allocation(*, output_mode: str = "text") -> None:
    """Analyze portfolio allocation."""
    command = "allocation"
    try:
        client = get_client()
        allocation = client.analyze_allocation()

        if output_mode == "json":
            print_json_response(command, data=allocation)
            return

        print(format_header("PORTFOLIO ALLOCATION"))

        # Asset class breakdown
        if allocation.get("by_asset_class"):
            print("\n  BY ASSET CLASS:")
            for asset_class, data in allocation["by_asset_class"].items():
                pct = data.get("percentage", 0)
                value = data.get("value", 0)
                print(f"    {asset_class:15s} {pct:>6.1f}%  {format_currency(value)}")

        # Top holdings
        if allocation.get("top_holdings"):
            print("\n  TOP HOLDINGS:")
            for holding in allocation["top_holdings"][:10]:
                symbol = holding.get("symbol", "???")
                pct = holding.get("percentage", 0)
                value = holding.get("value", 0)
                print(f"    {symbol:8s} {pct:>6.1f}%  {format_currency(value)}")

        # Concentration warnings
        if allocation.get("concentration_warnings"):
            print("\n  CONCENTRATION WARNINGS:")
            for warning in allocation["concentration_warnings"]:
                print(f"    - {warning}")

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_performance(*, output_mode: str = "text") -> None:
    """Show portfolio performance."""
    command = "performance"
    try:
        client = get_client()
        perf = client.get_portfolio_performance()

        if output_mode == "json":
            print_json_response(command, data=perf)
            return

        print(format_header("PORTFOLIO PERFORMANCE"))

        print(f"\n  Total Value:    {format_currency(perf.get('total_value'))}")
        print(f"  Day Change:     {format_currency(perf.get('day_change'))} ({format_percent(perf.get('day_change_percent'))})")

        if perf.get("top_gainers"):
            print("\n  TOP GAINERS:")
            for g in perf["top_gainers"][:5]:
                symbol = g.get("symbol", "???")
                change = g.get("day_gain_percent", 0)
                print(f"    {symbol:8s} +{change:.2f}%")

        if perf.get("top_losers"):
            print("\n  TOP LOSERS:")
            for l in perf["top_losers"][:5]:
                symbol = l.get("symbol", "???")
                change = l.get("day_gain_percent", 0)
                print(f"    {symbol:8s} {change:.2f}%")

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)
