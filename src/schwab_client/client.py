"""Enhanced Schwab client wrapper with project-specific features."""

from __future__ import annotations

from typing import Any

from config.secure_account_config import secure_config

from ._client import MONEY_MARKET_SYMBOLS, PortfolioClientMixin, TradingClientMixin


class SchwabClientWrapper(PortfolioClientMixin, TradingClientMixin):
    """Thin public wrapper around an authenticated ``schwab.Client`` instance."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._account_hashes: dict[str, str] | None = None

    @property
    def raw_client(self) -> Any:
        """Access the underlying ``schwab-py`` client for advanced operations."""
        return self._client


__all__ = ["MONEY_MARKET_SYMBOLS", "SchwabClientWrapper", "secure_config"]
