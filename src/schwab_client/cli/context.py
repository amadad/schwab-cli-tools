"""
CLI context with cached clients and shared state.

Provides lazy singletons for portfolio and market clients to avoid
redundant token I/O on every command.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..auth import get_authenticated_client, resolve_data_dir
from ..client import SchwabClientWrapper
from ..market_auth import get_market_client
from src.core.errors import ConfigError

logger = logging.getLogger(__name__)

# Module-level cached clients (lazy singletons)
_portfolio_client: SchwabClientWrapper | None = None
_market_client: Any | None = None
_trade_logger: logging.Logger | None = None


def get_client() -> SchwabClientWrapper:
    """Get cached portfolio client (lazy singleton).

    Creates client on first call, reuses on subsequent calls.
    Token file is read only once per CLI invocation.
    """
    global _portfolio_client
    if _portfolio_client is None:
        raw_client = get_authenticated_client()
        _portfolio_client = SchwabClientWrapper(raw_client)
    return _portfolio_client


def get_cached_market_client():
    """Get cached market client (lazy singleton).

    Creates client on first call, reuses on subsequent calls.
    """
    global _market_client
    if _market_client is None:
        try:
            _market_client = get_market_client()
        except Exception as exc:
            raise ConfigError(
                f"Market API not configured: {exc}. "
                "Run 'schwab-market-auth' or set SCHWAB_MARKET_APP_KEY."
            ) from exc
    return _market_client


def reset_clients() -> None:
    """Reset cached clients (for testing)."""
    global _portfolio_client, _market_client
    _portfolio_client = None
    _market_client = None


def get_trade_logger() -> logging.Logger:
    """Get or create the trade audit logger (lazy singleton)."""
    global _trade_logger
    if _trade_logger is not None:
        return _trade_logger

    # Determine log path
    log_path_env = os.getenv("SCHWAB_TRADE_AUDIT_LOG")
    if log_path_env:
        log_path = Path(log_path_env).expanduser()
    else:
        log_path = resolve_data_dir() / "trade_audit.log"

    log_path.parent.mkdir(parents=True, exist_ok=True)

    _trade_logger = logging.getLogger("schwab.trade_audit")
    _trade_logger.setLevel(logging.INFO)

    # Avoid duplicate handlers
    if not _trade_logger.handlers:
        handler = logging.FileHandler(log_path)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        _trade_logger.addHandler(handler)

    return _trade_logger


def log_trade_attempt(
    *,
    action: str,
    symbol: str,
    quantity: int,
    account_alias: str,
    limit_price: float | None = None,
    dry_run: bool = False,
    executed: bool = False,
    cancelled: bool = False,
    error: str | None = None,
) -> None:
    """Log all trade attempts for audit purposes."""
    logger = get_trade_logger()

    order_type = f"LIMIT@{limit_price}" if limit_price else "MARKET"

    if dry_run:
        status = "DRY_RUN"
    elif executed:
        status = "EXECUTED"
    elif cancelled:
        status = "CANCELLED"
    elif error:
        status = f"ERROR: {error}"
    else:
        status = "ATTEMPTED"

    logger.info(
        f"{action} | {symbol} | {quantity} | {order_type} | {account_alias} | {status}"
    )


@dataclass
class CommandContext:
    """Context object passed to command handlers.

    Provides access to cached clients and shared configuration.
    """
    output_mode: str = "text"
    _client: SchwabClientWrapper | None = field(default=None, repr=False)
    _market_client: Any | None = field(default=None, repr=False)

    @property
    def client(self) -> SchwabClientWrapper:
        """Lazy-load portfolio client."""
        if self._client is None:
            self._client = get_client()
        return self._client

    @property
    def market_client(self):
        """Lazy-load market client."""
        if self._market_client is None:
            self._market_client = get_cached_market_client()
        return self._market_client

    @property
    def is_json(self) -> bool:
        return self.output_mode == "json"
