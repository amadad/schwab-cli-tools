"""CLI command modules."""

from .admin import cmd_accounts, cmd_auth, cmd_doctor
from .market import (
    cmd_dividends,
    cmd_fundamentals,
    cmd_futures,
    cmd_indices,
    cmd_market,
    cmd_movers,
    cmd_sectors,
    cmd_vix,
)
from .portfolio import (
    cmd_allocation,
    cmd_balance,
    cmd_portfolio,
    cmd_positions,
)
from .report import cmd_report, cmd_snapshot
from .trade import cmd_buy, cmd_orders, cmd_sell

__all__ = [
    # Portfolio
    "cmd_portfolio",
    "cmd_positions",
    "cmd_balance",
    "cmd_allocation",
    # Market
    "cmd_vix",
    "cmd_indices",
    "cmd_sectors",
    "cmd_market",
    "cmd_movers",
    "cmd_futures",
    "cmd_fundamentals",
    "cmd_dividends",
    # Trade
    "cmd_buy",
    "cmd_sell",
    "cmd_orders",
    # Admin
    "cmd_auth",
    "cmd_doctor",
    "cmd_accounts",
    # Report
    "cmd_report",
    "cmd_snapshot",
]
