"""CLI command modules."""

from .admin import cmd_accounts, cmd_auth, cmd_auth_login, cmd_doctor
from .brief_cmd import cmd_brief
from .context_cmd import cmd_context
from .history import cmd_history, cmd_query
from .market import (
    cmd_dividends,
    cmd_fundamentals,
    cmd_futures,
    cmd_hours,
    cmd_indices,
    cmd_iv,
    cmd_lynch,
    cmd_market,
    cmd_movers,
    cmd_regime,
    cmd_score,
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
    # Context
    "cmd_context",
    # Brief
    "cmd_brief",
    # Portfolio
    "cmd_portfolio",
    "cmd_positions",
    "cmd_balance",
    "cmd_allocation",
    # Market
    "cmd_vix",
    "cmd_indices",
    "cmd_iv",
    "cmd_sectors",
    "cmd_market",
    "cmd_movers",
    "cmd_futures",
    "cmd_hours",
    "cmd_fundamentals",
    "cmd_dividends",
    "cmd_lynch",
    "cmd_score",
    "cmd_regime",
    # Trade
    "cmd_buy",
    "cmd_sell",
    "cmd_orders",
    # Admin
    "cmd_auth",
    "cmd_auth_login",
    "cmd_doctor",
    "cmd_accounts",
    # History
    "cmd_history",
    "cmd_query",
    # Report
    "cmd_report",
    "cmd_snapshot",
]
