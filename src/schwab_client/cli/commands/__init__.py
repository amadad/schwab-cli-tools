"""Lazy command-handler exports for the CLI."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module

_COMMAND_MODULES = {
    "cmd_accounts": "admin",
    "cmd_auth": "admin",
    "cmd_auth_login": "admin",
    "cmd_doctor": "admin",
    "cmd_brief": "brief_cmd",
    "cmd_context": "context_cmd",
    "cmd_history": "history",
    "cmd_query": "history",
    "cmd_dividends": "market",
    "cmd_fundamentals": "market",
    "cmd_futures": "market",
    "cmd_hours": "market",
    "cmd_indices": "market",
    "cmd_iv": "market",
    "cmd_lynch": "market",
    "cmd_market": "market",
    "cmd_movers": "market",
    "cmd_regime": "market",
    "cmd_score": "market",
    "cmd_sectors": "market",
    "cmd_vix": "market",
    "cmd_allocation": "portfolio",
    "cmd_balance": "portfolio",
    "cmd_portfolio": "portfolio",
    "cmd_positions": "portfolio",
    "cmd_report": "report",
    "cmd_snapshot": "report",
    "cmd_buy": "trade",
    "cmd_orders": "trade",
    "cmd_sell": "trade",
}


def get_command(name: str) -> Callable[..., object]:
    module_name = _COMMAND_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no command {name!r}")
    module = import_module(f"{__name__}.{module_name}")
    command = getattr(module, name)
    globals()[name] = command
    return command


def __getattr__(name: str) -> Callable[..., object]:
    return get_command(name)


__all__ = ["get_command", *_COMMAND_MODULES]
