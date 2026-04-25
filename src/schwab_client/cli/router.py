"""Command routing for the Schwab CLI."""

from __future__ import annotations

import sys

try:
    import argcomplete

    ARGCOMPLETE_AVAILABLE = True
except ImportError:
    ARGCOMPLETE_AVAILABLE = False

from .commands import get_command
from .parser import COMMAND_ALIASES, build_parser, resolve_output_mode


def _handler(name: str):
    return globals().get(name) or get_command(name)


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
        _handler("cmd_portfolio")(
            output_mode=output_mode,
            include_positions=getattr(parsed, "positions", False),
        )
    elif parsed.command == "positions":
        _handler("cmd_positions")(output_mode=output_mode, symbol=getattr(parsed, "symbol", None))
    elif parsed.command == "balance":
        _handler("cmd_balance")(output_mode=output_mode)
    elif parsed.command == "allocation":
        _handler("cmd_allocation")(output_mode=output_mode)
    elif parsed.command == "vix":
        _handler("cmd_vix")(output_mode=output_mode)
    elif parsed.command == "indices":
        _handler("cmd_indices")(output_mode=output_mode)
    elif parsed.command == "sectors":
        _handler("cmd_sectors")(output_mode=output_mode)
    elif parsed.command == "market":
        _handler("cmd_market")(output_mode=output_mode)
    elif parsed.command == "movers":
        _handler("cmd_movers")(
            output_mode=output_mode,
            gainers_only=getattr(parsed, "gainers", False),
            losers_only=getattr(parsed, "losers", False),
            count=getattr(parsed, "count", 5),
            index=getattr(parsed, "index", "SPX"),
        )
    elif parsed.command == "futures":
        _handler("cmd_futures")(output_mode=output_mode)
    elif parsed.command == "hours":
        _handler("cmd_hours")(date=getattr(parsed, "date", None), output_mode=output_mode)
    elif parsed.command == "fundamentals":
        _handler("cmd_fundamentals")(parsed.symbol, output_mode=output_mode)
    elif parsed.command == "iv":
        _handler("cmd_iv")(parsed.symbol, output_mode=output_mode)
    elif parsed.command == "dividends":
        _handler("cmd_dividends")(
            days=getattr(parsed, "days", 30),
            output_mode=output_mode,
            upcoming=getattr(parsed, "upcoming", False),
        )
    elif parsed.command == "lynch":
        _handler("cmd_lynch")(output_mode=output_mode)
    elif parsed.command == "regime":
        _handler("cmd_regime")(output_mode=output_mode)
    elif parsed.command == "score":
        _handler("cmd_score")(parsed.symbol, output_mode=output_mode)
    elif parsed.command == "context":
        _handler("cmd_context")(
            output_mode=output_mode,
            include_lynch=getattr(parsed, "lynch", False),
            prompt=getattr(parsed, "prompt", False),
            template=getattr(parsed, "template", None),
            output_path=getattr(parsed, "output", None),
        )
    elif parsed.command == "brief":
        action = getattr(parsed, "brief_action", None) or "status"
        _handler("cmd_brief")(
            action=action,
            output_mode=output_mode,
            reuse_snapshot_id=getattr(parsed, "reuse_snapshot_id", None),
            brief_for_date=getattr(parsed, "for_date", None),
            dry_run=getattr(parsed, "dry_run", False),
            force=getattr(parsed, "force", False),
            run_id=getattr(parsed, "run_id", None),
            limit=getattr(parsed, "limit", 10),
        )
    elif parsed.command == "auth":
        auth_action = getattr(parsed, "auth_action", "status")
        auth_rail = "market" if getattr(parsed, "market", False) else "portfolio"
        if auth_action == "login":
            _handler("cmd_auth_login")(
                output_mode=output_mode,
                rail=auth_rail,
                force=getattr(parsed, "force", False),
                manual=getattr(parsed, "manual", False),
                interactive=getattr(parsed, "interactive", False),
                browser=getattr(parsed, "browser", None),
                timeout=getattr(parsed, "timeout", 300.0),
            )
        else:
            _handler("cmd_auth")(output_mode=output_mode, rail=auth_rail)
    elif parsed.command == "doctor":
        _handler("cmd_doctor")(output_mode=output_mode)
    elif parsed.command == "accounts":
        _handler("cmd_accounts")(output_mode=output_mode)
    elif parsed.command == "history":
        import_paths = getattr(parsed, "import_paths", None)
        if getattr(parsed, "import_defaults", False):
            import_paths = []
        _handler("cmd_history")(
            output_mode=output_mode,
            dataset=getattr(parsed, "dataset", "runs"),
            limit=getattr(parsed, "limit", 20),
            since=getattr(parsed, "since", None),
            symbol=getattr(parsed, "symbol", None),
            account=getattr(parsed, "account", None),
            snapshot_id=getattr(parsed, "snapshot_id", None),
            output_path=getattr(parsed, "output", None),
            backfill_paths=import_paths,
        )
    elif parsed.command == "query":
        _handler("cmd_query")(parsed.sql, output_mode=output_mode)
    elif parsed.command == "report":
        _handler("cmd_report")(
            output_mode=output_mode,
            output_path=getattr(parsed, "output", None),
            include_market=not getattr(parsed, "no_market", False),
        )
    elif parsed.command == "snapshot":
        _handler("cmd_snapshot")(
            output_mode=output_mode,
            output_path=getattr(parsed, "output", None),
            include_market=not getattr(parsed, "no_market", False),
        )
    elif parsed.command == "buy":
        _handler("cmd_buy")(
            getattr(parsed, "args", []),
            limit_price=getattr(parsed, "limit", None),
            dry_run=getattr(parsed, "dry_run", False),
            live=getattr(parsed, "live", False),
            output_mode=output_mode,
            auto_confirm=getattr(parsed, "yes", False),
            non_interactive=non_interactive,
        )
    elif parsed.command == "sell":
        _handler("cmd_sell")(
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
        _handler("cmd_orders")(getattr(parsed, "args", []), output_mode=output_mode)
    else:
        parser.print_help()
        sys.exit(1)

