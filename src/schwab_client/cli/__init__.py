"""
Schwab CLI - Command-line interface for portfolio management.

Usage:
    schwab <command> [options]

Commands:
    portfolio    Show portfolio summary
    positions    Show positions
    balance      Show account balances
    allocation   Analyze allocation
    vix          Show VIX data
    indices      Show market indices
    sectors      Show sector performance
    market       Show market signals
    movers       Show top gainers/losers
    futures      Show pre-market futures
    fundamentals Show symbol fundamentals
    dividends    Show dividends
    auth         Check authentication
    doctor       Run diagnostics
    accounts     List accounts
    report       Generate report
    snapshot     Get data snapshot
    buy          Buy shares
    sell         Sell shares
    orders       Show orders
"""

import argparse
import os
import sys
from importlib.metadata import version as get_version

try:
    import argcomplete
    ARGCOMPLETE_AVAILABLE = True
except ImportError:
    ARGCOMPLETE_AVAILABLE = False

from .commands import (
    cmd_accounts,
    cmd_allocation,
    cmd_auth,
    cmd_balance,
    cmd_buy,
    cmd_dividends,
    cmd_doctor,
    cmd_fundamentals,
    cmd_futures,
    cmd_indices,
    cmd_market,
    cmd_movers,
    cmd_orders,
    cmd_portfolio,
    cmd_positions,
    cmd_report,
    cmd_sectors,
    cmd_sell,
    cmd_snapshot,
    cmd_vix,
)

__version__ = get_version("schwab-cli-tools")

OUTPUT_ENV_VAR = "SCHWAB_OUTPUT"

# Command aliases for ergonomics
COMMAND_ALIASES = {
    "p": "portfolio",
    "pos": "positions",
    "bal": "balance",
    "alloc": "allocation",
    "idx": "indices",
    "sec": "sectors",
    "mkt": "market",
    "mov": "movers",
    "fut": "futures",
    "fund": "fundamentals",
    "div": "dividends",
    "dr": "doctor",
    "snap": "snapshot",
    "ord": "orders",
}


def resolve_output_mode(parsed_args) -> str:
    """Resolve output mode from args or environment."""
    if getattr(parsed_args, "json", False):
        return "json"
    if getattr(parsed_args, "text", False):
        return "text"
    env_output = os.getenv(OUTPUT_ENV_VAR, "").lower()
    if env_output in ("json", "text"):
        return env_output
    return "text"


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    common_parser = argparse.ArgumentParser(add_help=False)
    output_group = common_parser.add_mutually_exclusive_group()
    output_group.add_argument("--json", action="store_true", help="Output as JSON")
    output_group.add_argument("--text", action="store_true", help="Output as text")
    common_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Fail if interactive input would be required",
    )

    parser = argparse.ArgumentParser(
        prog="schwab",
        description="Schwab CLI for portfolio management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Aliases:
  p=portfolio, pos=positions, bal=balance, alloc=allocation,
  idx=indices, sec=sectors, mkt=market,
  mov=movers, fut=futures, fund=fundamentals, div=dividends,
  dr=doctor, snap=snapshot, ord=orders

Examples:
  schwab portfolio --json
  schwab p -p                  # portfolio with positions
  schwab positions --symbol AAPL
  schwab buy acct_trading AAPL 10 --dry-run
  schwab dr                    # doctor diagnostics
""",
    )
    parser.add_argument(
        "--version", "-V", action="version", version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Portfolio commands
    portfolio_parser = subparsers.add_parser(
        "portfolio", aliases=["p"], help="Show portfolio summary", parents=[common_parser]
    )
    portfolio_parser.add_argument(
        "-p", "--positions", action="store_true", help="Include positions"
    )

    positions_parser = subparsers.add_parser(
        "positions", aliases=["pos"], help="Show positions", parents=[common_parser]
    )
    positions_parser.add_argument("--symbol", help="Filter by symbol")

    subparsers.add_parser(
        "balance", aliases=["bal"], help="Show account balances", parents=[common_parser]
    )
    subparsers.add_parser(
        "allocation", aliases=["alloc"], help="Analyze allocation", parents=[common_parser]
    )
    # Market commands
    subparsers.add_parser("vix", help="Show VIX data", parents=[common_parser])
    subparsers.add_parser(
        "indices", aliases=["idx"], help="Show market indices", parents=[common_parser]
    )
    subparsers.add_parser(
        "sectors", aliases=["sec"], help="Show sector performance", parents=[common_parser]
    )
    subparsers.add_parser(
        "market", aliases=["mkt"], help="Show market signals", parents=[common_parser]
    )

    movers_parser = subparsers.add_parser(
        "movers", aliases=["mov"], help="Show top movers", parents=[common_parser]
    )
    movers_parser.add_argument("--gainers", action="store_true", help="Gainers only")
    movers_parser.add_argument("--losers", action="store_true", help="Losers only")
    movers_parser.add_argument("--count", type=int, default=5, help="Number to show")

    subparsers.add_parser(
        "futures", aliases=["fut"], help="Show pre-market futures", parents=[common_parser]
    )

    fundamentals_parser = subparsers.add_parser(
        "fundamentals", aliases=["fund"], help="Show fundamentals", parents=[common_parser]
    )
    fundamentals_parser.add_argument("symbol", help="Symbol to look up")

    dividends_parser = subparsers.add_parser(
        "dividends", aliases=["div"], help="Show dividends", parents=[common_parser]
    )
    dividends_parser.add_argument("--days", type=int, default=30, help="Days to look back")
    dividends_parser.add_argument("--upcoming", action="store_true", help="Show upcoming ex-dates")

    # Admin commands
    subparsers.add_parser("auth", help="Check authentication", parents=[common_parser])
    subparsers.add_parser(
        "doctor", aliases=["dr"], help="Run diagnostics", parents=[common_parser]
    )
    subparsers.add_parser("accounts", help="List accounts", parents=[common_parser])

    # Report commands
    report_parser = subparsers.add_parser(
        "report", help="Generate portfolio report", parents=[common_parser]
    )
    report_parser.add_argument("--output", "-o", help="Output path")
    report_parser.add_argument(
        "--no-market", action="store_true", help="Skip market data"
    )

    subparsers.add_parser(
        "snapshot", aliases=["snap"], help="Get data snapshot", parents=[common_parser]
    )

    # Trade commands
    buy_parser = subparsers.add_parser("buy", help="Buy shares", parents=[common_parser])
    buy_parser.add_argument(
        "args", nargs="*", metavar="[ACCOUNT] SYMBOL QTY", help="Trade arguments"
    )
    buy_parser.add_argument("--limit", type=float, help="Limit price")
    buy_parser.add_argument("--dry-run", action="store_true", help="Preview only")
    buy_parser.add_argument("--live", action="store_true", help="Enable live trading for this command")
    buy_parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")

    sell_parser = subparsers.add_parser("sell", help="Sell shares", parents=[common_parser])
    sell_parser.add_argument(
        "args", nargs="*", metavar="[ACCOUNT] SYMBOL QTY", help="Trade arguments"
    )
    sell_parser.add_argument("--limit", type=float, help="Limit price")
    sell_parser.add_argument("--dry-run", action="store_true", help="Preview only")
    sell_parser.add_argument("--live", action="store_true", help="Enable live trading for this command")
    sell_parser.add_argument("--all", action="store_true", dest="sell_all", help="Sell entire position")
    sell_parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")

    orders_parser = subparsers.add_parser(
        "orders", aliases=["ord"], help="Show orders", parents=[common_parser]
    )
    orders_parser.add_argument("args", nargs="*", metavar="[ACCOUNT]", help="Account")

    return parser


def main(args: list | None = None) -> None:
    """Main CLI entry point."""
    parser = build_parser()

    # Enable shell completion if argcomplete is installed
    if ARGCOMPLETE_AVAILABLE:
        argcomplete.autocomplete(parser)

    parsed = parser.parse_args(args)

    # Resolve aliases
    if parsed.command in COMMAND_ALIASES:
        parsed.command = COMMAND_ALIASES[parsed.command]

    if not parsed.command:
        parser.print_help()
        sys.exit(0)

    output_mode = resolve_output_mode(parsed)
    non_interactive = getattr(parsed, "non_interactive", False)

    # Route to command handlers
    if parsed.command == "portfolio":
        cmd_portfolio(
            output_mode=output_mode,
            include_positions=getattr(parsed, "positions", False),
        )
    elif parsed.command == "positions":
        cmd_positions(output_mode=output_mode, symbol=getattr(parsed, "symbol", None))
    elif parsed.command == "balance":
        cmd_balance(output_mode=output_mode)
    elif parsed.command == "allocation":
        cmd_allocation(output_mode=output_mode)
    elif parsed.command == "vix":
        cmd_vix(output_mode=output_mode)
    elif parsed.command == "indices":
        cmd_indices(output_mode=output_mode)
    elif parsed.command == "sectors":
        cmd_sectors(output_mode=output_mode)
    elif parsed.command == "market":
        cmd_market(output_mode=output_mode)
    elif parsed.command == "movers":
        cmd_movers(
            output_mode=output_mode,
            gainers_only=getattr(parsed, "gainers", False),
            losers_only=getattr(parsed, "losers", False),
            count=getattr(parsed, "count", 5),
        )
    elif parsed.command == "futures":
        cmd_futures(output_mode=output_mode)
    elif parsed.command == "fundamentals":
        cmd_fundamentals(parsed.symbol, output_mode=output_mode)
    elif parsed.command == "dividends":
        cmd_dividends(
            days=getattr(parsed, "days", 30),
            output_mode=output_mode,
            upcoming=getattr(parsed, "upcoming", False),
        )
    elif parsed.command == "auth":
        cmd_auth(output_mode=output_mode)
    elif parsed.command == "doctor":
        cmd_doctor(output_mode=output_mode)
    elif parsed.command == "accounts":
        cmd_accounts(output_mode=output_mode)
    elif parsed.command == "report":
        cmd_report(
            output_mode=output_mode,
            output_path=getattr(parsed, "output", None),
            include_market=not getattr(parsed, "no_market", False),
        )
    elif parsed.command == "snapshot":
        cmd_snapshot(output_mode=output_mode)
    elif parsed.command == "buy":
        cmd_buy(
            getattr(parsed, "args", []),
            limit_price=getattr(parsed, "limit", None),
            dry_run=getattr(parsed, "dry_run", False),
            live=getattr(parsed, "live", False),
            output_mode=output_mode,
            auto_confirm=getattr(parsed, "yes", False),
            non_interactive=non_interactive,
        )
    elif parsed.command == "sell":
        cmd_sell(
            getattr(parsed, "args", []),
            limit_price=getattr(parsed, "limit", None),
            dry_run=getattr(parsed, "dry_run", False),
            live=getattr(parsed, "live", False),
            sell_all=getattr(parsed, "sell_all", False),
            output_mode=output_mode,
            auto_confirm=getattr(parsed, "yes", False),
            non_interactive=non_interactive,
        )
    elif parsed.command == "orders":
        cmd_orders(getattr(parsed, "args", []), output_mode=output_mode)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
