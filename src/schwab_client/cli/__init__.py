"""Schwab CLI package entrypoint."""

from __future__ import annotations

from . import router as _router
from .commands import get_command
from .parser import COMMAND_ALIASES, OUTPUT_ENV_VAR, __version__, build_parser, resolve_output_mode

_COMMAND_NAMES = [
    "cmd_accounts",
    "cmd_allocation",
    "cmd_auth",
    "cmd_auth_login",
    "cmd_balance",
    "cmd_brief",
    "cmd_buy",
    "cmd_context",
    "cmd_dividends",
    "cmd_doctor",
    "cmd_fundamentals",
    "cmd_futures",
    "cmd_history",
    "cmd_hours",
    "cmd_indices",
    "cmd_iv",
    "cmd_lynch",
    "cmd_market",
    "cmd_movers",
    "cmd_orders",
    "cmd_portfolio",
    "cmd_positions",
    "cmd_query",
    "cmd_regime",
    "cmd_report",
    "cmd_score",
    "cmd_sectors",
    "cmd_sell",
    "cmd_snapshot",
    "cmd_vix",
]


def __getattr__(name: str):
    if name in _COMMAND_NAMES:
        command = get_command(name)
        globals()[name] = command
        return command
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main(args: list | None = None) -> None:
    """Run the CLI, preserving package-level command patch points for tests."""
    for name in _COMMAND_NAMES:
        if name in globals():
            setattr(_router, name, globals()[name])
    _router.main(args)


__all__ = [
    "COMMAND_ALIASES",
    "OUTPUT_ENV_VAR",
    "__version__",
    "build_parser",
    "cmd_accounts",
    "cmd_allocation",
    "cmd_auth",
    "cmd_auth_login",
    "cmd_balance",
    "cmd_brief",
    "cmd_buy",
    "cmd_context",
    "cmd_dividends",
    "cmd_doctor",
    "cmd_fundamentals",
    "cmd_futures",
    "cmd_history",
    "cmd_hours",
    "cmd_indices",
    "cmd_iv",
    "cmd_lynch",
    "cmd_market",
    "cmd_movers",
    "cmd_orders",
    "cmd_portfolio",
    "cmd_positions",
    "cmd_query",
    "cmd_regime",
    "cmd_report",
    "cmd_score",
    "cmd_sectors",
    "cmd_sell",
    "cmd_snapshot",
    "cmd_vix",
    "main",
    "resolve_output_mode",
]
