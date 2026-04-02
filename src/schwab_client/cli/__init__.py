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
    regime       Show market regime (risk-on/off)
    auth         Check authentication
    doctor       Run diagnostics
    accounts     List accounts
    history      Query stored snapshot history
    query        Run read-only SQL against snapshot history
    report       Export snapshot JSON
    snapshot     Capture data snapshot
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
    cmd_advisor_close,
    cmd_advisor_evaluate,
    cmd_advisor_learn,
    cmd_advisor_review,
    cmd_advisor_status,
    cmd_advisor_thesis,
    cmd_allocation,
    cmd_auth,
    cmd_balance,
    cmd_buy,
    cmd_context,
    cmd_dividends,
    cmd_doctor,
    cmd_fundamentals,
    cmd_futures,
    cmd_history,
    cmd_hours,
    cmd_indices,
    cmd_iv,
    cmd_lynch,
    cmd_market,
    cmd_movers,
    cmd_orders,
    cmd_portfolio,
    cmd_positions,
    cmd_query,
    cmd_regime,
    cmd_report,
    cmd_score,
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
    "ctx": "context",
    "ly": "lynch",
    "reg": "regime",
    "adv": "advisor",
    "dr": "doctor",
    "hist": "history",
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
  ctx=context, ly=lynch, reg=regime,
  dr=doctor, hist=history, snap=snapshot, ord=orders

Examples:
  schwab portfolio --json
  schwab p -p                  # portfolio with positions
  schwab positions --symbol AAPL
  schwab history --dataset portfolio --limit 10
  schwab query "SELECT * FROM portfolio_history LIMIT 5"
  schwab snapshot --json
  schwab context --json
  schwab context -t memo
  schwab snapshot --output ./private/reports/latest.json
  schwab buy acct_trading AAPL 10 --dry-run
  schwab dr                    # doctor diagnostics
""",
    )
    parser.add_argument("--version", "-V", action="version", version=f"%(prog)s {__version__}")

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
    movers_parser.add_argument(
        "--index",
        default="SPX",
        choices=["SPX", "NASDAQ", "NYSE", "DJI"],
        help="Index to show movers for (default: SPX)",
    )

    subparsers.add_parser(
        "futures", aliases=["fut"], help="Show pre-market futures", parents=[common_parser]
    )

    hours_parser = subparsers.add_parser(
        "hours", help="Check market hours", parents=[common_parser]
    )
    hours_parser.add_argument("--date", help="Date to check (YYYY-MM-DD)")

    fundamentals_parser = subparsers.add_parser(
        "fundamentals", aliases=["fund"], help="Show fundamentals", parents=[common_parser]
    )
    fundamentals_parser.add_argument("symbol", help="Symbol to look up")

    iv_parser = subparsers.add_parser("iv", help="Show implied volatility", parents=[common_parser])
    iv_parser.add_argument("symbol", help="Symbol to look up")

    dividends_parser = subparsers.add_parser(
        "dividends", aliases=["div"], help="Show dividends", parents=[common_parser]
    )
    dividends_parser.add_argument("--days", type=int, default=30, help="Days to look back")
    dividends_parser.add_argument("--upcoming", action="store_true", help="Show upcoming ex-dates")

    subparsers.add_parser(
        "lynch", aliases=["ly"], help="Check Lynch sell signals", parents=[common_parser]
    )

    subparsers.add_parser(
        "regime", aliases=["reg"], help="Show market regime (risk-on/off)", parents=[common_parser]
    )

    score_parser = subparsers.add_parser(
        "score", help="Score a stock (quality framework)", parents=[common_parser]
    )
    score_parser.add_argument("symbol", help="Symbol to score")

    # Context command
    context_parser = subparsers.add_parser(
        "context",
        aliases=["ctx"],
        help="Assemble full portfolio context",
        parents=[common_parser],
    )
    context_parser.add_argument(
        "--lynch",
        action="store_true",
        default=True,
        help="Include Lynch sell signals (use --no-lynch to skip)",
    )
    context_parser.add_argument(
        "--no-lynch",
        dest="lynch",
        action="store_false",
        help="Skip Lynch sell signals for faster output",
    )
    context_parser.add_argument(
        "--prompt",
        action="store_true",
        help="Output as an LLM-ready prompt block",
    )
    context_parser.add_argument(
        "--template",
        "-t",
        choices=["brief", "review", "memo"],
        help="Wrap context in a prompt template (brief/review/memo)",
    )

    # Advisor learning loop
    advisor_parser = subparsers.add_parser(
        "advisor",
        aliases=["adv"],
        help="Portfolio advisor learning loop",
        parents=[common_parser],
    )
    advisor_sub = advisor_parser.add_subparsers(dest="advisor_command", help="Advisor commands")

    thesis_parser = advisor_sub.add_parser("thesis", help="Record an investment thesis")
    thesis_parser.add_argument("symbol", help="Symbol for the thesis")
    thesis_parser.add_argument(
        "--direction", "-d", default="long", choices=["long", "short"],
        help="Trade direction (default: long)",
    )
    thesis_parser.add_argument(
        "--rationale", "-r", default="", help="Investment rationale",
    )
    thesis_parser.add_argument(
        "--horizon", type=int, default=90, help="Time horizon in days (default: 90)",
    )
    thesis_parser.add_argument("--entry-price", type=float, help="Entry price")
    thesis_parser.add_argument("--target", type=float, help="Target return %%")
    thesis_parser.add_argument("--stop-loss", type=float, help="Stop loss %%")
    thesis_parser.add_argument("--tags", help="Comma-separated tags")

    advisor_sub.add_parser("evaluate", help="Evaluate open theses against current prices")

    review_parser = advisor_sub.add_parser("review", help="Show thesis history and reviews")
    review_parser.add_argument("--id", type=int, dest="thesis_id", help="Show specific thesis")
    review_parser.add_argument(
        "--status", choices=["open", "closed"], help="Filter by status",
    )
    review_parser.add_argument("--limit", type=int, default=20, help="Max results")

    learn_parser = advisor_sub.add_parser("learn", help="Extract patterns / generate learning prompts")
    learn_parser.add_argument(
        "--prompt", action="store_true", help="Output learning context as LLM-ready text",
    )
    learn_parser.add_argument(
        "--template", "-t", choices=["retrospective", "patterns", "scan"],
        help="Wrap learning context in an advisor prompt template",
    )

    advisor_sub.add_parser("status", help="Show learning loop dashboard")

    close_parser = advisor_sub.add_parser("close", help="Close an open thesis")
    close_parser.add_argument("thesis_id", type=int, help="Thesis ID to close")
    close_parser.add_argument("--reason", default="manual", help="Close reason")

    # Admin commands
    subparsers.add_parser("auth", help="Check authentication", parents=[common_parser])
    subparsers.add_parser("doctor", aliases=["dr"], help="Run diagnostics", parents=[common_parser])
    subparsers.add_parser("accounts", help="List accounts", parents=[common_parser])

    history_parser = subparsers.add_parser(
        "history", aliases=["hist"], help="Query stored snapshot history", parents=[common_parser]
    )
    history_parser.add_argument(
        "--dataset",
        choices=["runs", "portfolio", "positions", "market"],
        default="runs",
        help="History dataset to query (default: runs)",
    )
    history_parser.add_argument("--limit", type=int, default=20, help="Rows to return")
    history_parser.add_argument(
        "--since", help="Only include rows since YYYY-MM-DD or ISO timestamp"
    )
    history_parser.add_argument("--symbol", help="Filter position history by symbol")
    history_parser.add_argument("--account", help="Filter position history by account label/alias")
    history_parser.add_argument(
        "--import",
        dest="import_paths",
        action="append",
        metavar="PATH",
        help=(
            "Import existing JSON history from a file or directory. "
            "Repeat for multiple paths; omit PATH to import default snapshot/report dirs."
        ),
    )
    history_parser.add_argument(
        "--import-defaults",
        action="store_true",
        help="Import default snapshot/report directories into the history database",
    )

    query_parser = subparsers.add_parser(
        "query", help="Run read-only SQL against the history database", parents=[common_parser]
    )
    query_parser.add_argument("sql", help="Read-only SQL query")

    # Report commands
    report_parser = subparsers.add_parser(
        "report", help="Export canonical snapshot JSON", parents=[common_parser]
    )
    report_parser.add_argument(
        "--output",
        "-o",
        nargs="?",
        const="",
        help="Optional output path; omit value to use the default report location",
    )
    report_parser.add_argument("--no-market", action="store_true", help="Skip market data")

    snapshot_parser = subparsers.add_parser(
        "snapshot", aliases=["snap"], help="Capture canonical snapshot", parents=[common_parser]
    )
    snapshot_parser.add_argument(
        "--output",
        "-o",
        nargs="?",
        const="",
        help="Optional output path; omit value to use the default report location",
    )
    snapshot_parser.add_argument("--no-market", action="store_true", help="Skip market data")

    # Trade commands
    buy_parser = subparsers.add_parser("buy", help="Buy shares", parents=[common_parser])
    buy_parser.add_argument(
        "args", nargs="*", metavar="[ACCOUNT] SYMBOL QTY", help="Trade arguments"
    )
    buy_parser.add_argument("--limit", type=float, help="Limit price")
    buy_parser.add_argument("--dry-run", action="store_true", help="Preview only")
    buy_parser.add_argument(
        "--live", action="store_true", help="Enable live trading for this command"
    )
    buy_parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")

    sell_parser = subparsers.add_parser("sell", help="Sell shares", parents=[common_parser])
    sell_parser.add_argument(
        "args", nargs="*", metavar="[ACCOUNT] SYMBOL QTY", help="Trade arguments"
    )
    sell_parser.add_argument("--limit", type=float, help="Limit price")
    sell_parser.add_argument("--stop", type=float, help="Stop price (triggers sell when reached)")
    sell_parser.add_argument(
        "--trailing-stop",
        type=float,
        dest="trailing_stop",
        metavar="PCT",
        help="Trailing stop percentage from mark",
    )
    sell_parser.add_argument("--dry-run", action="store_true", help="Preview only")
    sell_parser.add_argument(
        "--live", action="store_true", help="Enable live trading for this command"
    )
    sell_parser.add_argument(
        "--all", action="store_true", dest="sell_all", help="Sell entire position"
    )
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
            index=getattr(parsed, "index", "SPX"),
        )
    elif parsed.command == "futures":
        cmd_futures(output_mode=output_mode)
    elif parsed.command == "hours":
        cmd_hours(date=getattr(parsed, "date", None), output_mode=output_mode)
    elif parsed.command == "fundamentals":
        cmd_fundamentals(parsed.symbol, output_mode=output_mode)
    elif parsed.command == "iv":
        cmd_iv(parsed.symbol, output_mode=output_mode)
    elif parsed.command == "dividends":
        cmd_dividends(
            days=getattr(parsed, "days", 30),
            output_mode=output_mode,
            upcoming=getattr(parsed, "upcoming", False),
        )
    elif parsed.command == "lynch":
        cmd_lynch(output_mode=output_mode)
    elif parsed.command == "regime":
        cmd_regime(output_mode=output_mode)
    elif parsed.command == "score":
        cmd_score(parsed.symbol, output_mode=output_mode)
    elif parsed.command == "context":
        cmd_context(
            output_mode=output_mode,
            include_lynch=getattr(parsed, "lynch", False),
            prompt=getattr(parsed, "prompt", False),
            template=getattr(parsed, "template", None),
        )
    elif parsed.command == "advisor":
        advisor_cmd = getattr(parsed, "advisor_command", None)
        if advisor_cmd == "thesis":
            tags = getattr(parsed, "tags", None)
            tag_list = [t.strip() for t in tags.split(",")] if tags else None
            cmd_advisor_thesis(
                parsed.symbol,
                direction=getattr(parsed, "direction", "long"),
                rationale=getattr(parsed, "rationale", ""),
                horizon=getattr(parsed, "horizon", 90),
                entry_price=getattr(parsed, "entry_price", None),
                target=getattr(parsed, "target", None),
                stop_loss=getattr(parsed, "stop_loss", None),
                tags=tag_list,
                output_mode=output_mode,
            )
        elif advisor_cmd == "evaluate":
            cmd_advisor_evaluate(output_mode=output_mode)
        elif advisor_cmd == "review":
            cmd_advisor_review(
                thesis_id=getattr(parsed, "thesis_id", None),
                status=getattr(parsed, "status", None),
                limit=getattr(parsed, "limit", 20),
                output_mode=output_mode,
            )
        elif advisor_cmd == "learn":
            cmd_advisor_learn(
                output_mode=output_mode,
                prompt=getattr(parsed, "prompt", False),
                template=getattr(parsed, "template", None),
            )
        elif advisor_cmd == "status":
            cmd_advisor_status(output_mode=output_mode)
        elif advisor_cmd == "close":
            cmd_advisor_close(
                parsed.thesis_id,
                reason=getattr(parsed, "reason", "manual"),
                output_mode=output_mode,
            )
        else:
            # No subcommand — show advisor help
            # Re-parse to get the advisor parser for help display
            parser.parse_args(["advisor", "--help"])
    elif parsed.command == "auth":
        cmd_auth(output_mode=output_mode)
    elif parsed.command == "doctor":
        cmd_doctor(output_mode=output_mode)
    elif parsed.command == "accounts":
        cmd_accounts(output_mode=output_mode)
    elif parsed.command == "history":
        import_paths = getattr(parsed, "import_paths", None)
        if getattr(parsed, "import_defaults", False):
            import_paths = []
        cmd_history(
            output_mode=output_mode,
            dataset=getattr(parsed, "dataset", "runs"),
            limit=getattr(parsed, "limit", 20),
            since=getattr(parsed, "since", None),
            symbol=getattr(parsed, "symbol", None),
            account=getattr(parsed, "account", None),
            backfill_paths=import_paths,
        )
    elif parsed.command == "query":
        cmd_query(parsed.sql, output_mode=output_mode)
    elif parsed.command == "report":
        cmd_report(
            output_mode=output_mode,
            output_path=getattr(parsed, "output", None),
            include_market=not getattr(parsed, "no_market", False),
        )
    elif parsed.command == "snapshot":
        cmd_snapshot(
            output_mode=output_mode,
            output_path=getattr(parsed, "output", None),
            include_market=not getattr(parsed, "no_market", False),
        )
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
            stop_price=getattr(parsed, "stop", None),
            trailing_stop_percent=getattr(parsed, "trailing_stop", None),
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
