"""Portfolio, account, and market-data methods for the Schwab client wrapper."""

from __future__ import annotations

from typing import Any

from src.core.portfolio_service import (
    analyze_allocation,
    build_account_balances,
    build_portfolio_summary,
    build_positions,
)

from .common import MONEY_MARKET_SYMBOLS, _retry_on_transient_error


class PortfolioClientMixin:
    """Mixin providing read-oriented Schwab account and quote methods."""

    @_retry_on_transient_error()
    def get_account_numbers(self) -> list[dict[str, str]]:
        """Get account numbers with hash values."""
        response = self._client.get_account_numbers()
        response.raise_for_status()
        accounts = response.json()
        self._account_hashes = {
            account["accountNumber"]: account["hashValue"] for account in accounts
        }
        return accounts

    def get_account_hash(self, account_number: str) -> str | None:
        """Get hash value for an account number."""
        if self._account_hashes is None:
            self.get_account_numbers()
        return self._account_hashes.get(account_number) if self._account_hashes else None

    @_retry_on_transient_error()
    def get_account(self, account_hash: str, include_positions: bool = True) -> dict[str, Any]:
        """Get account details by hash value."""
        if include_positions:
            response = self._client.get_account(
                account_hash,
                fields=self._client.Account.Fields.POSITIONS,
            )
        else:
            response = self._client.get_account(account_hash)

        response.raise_for_status()
        return response.json()

    @_retry_on_transient_error()
    def get_all_accounts_full(self) -> list[dict[str, Any]]:
        """Get all accounts with positions."""
        response = self._client.get_accounts(fields=self._client.Account.Fields.POSITIONS)
        response.raise_for_status()
        return response.json()

    def get_portfolio_summary(self) -> dict[str, Any]:
        """Get comprehensive portfolio summary with cash/invested breakdown."""
        accounts = self.get_all_accounts_full()
        return build_portfolio_summary(
            accounts,
            self._get_account_display_name,
            MONEY_MARKET_SYMBOLS,
        )

    def get_positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Get detailed positions across all accounts."""
        accounts = self.get_all_accounts_full()
        return build_positions(accounts, self._get_account_display_name, symbol)

    def get_account_balances(self) -> list[dict[str, Any]]:
        """Get balances for all accounts."""
        accounts = self.get_all_accounts_full()
        return build_account_balances(
            accounts,
            self._get_account_display_name,
            MONEY_MARKET_SYMBOLS,
        )

    def analyze_allocation(self) -> dict[str, Any]:
        """Analyze portfolio allocation and concentration."""
        accounts = self.get_all_accounts_full()
        return analyze_allocation(accounts)

    @_retry_on_transient_error()
    def get_quote(self, symbol: str) -> dict[str, Any]:
        """Get quote for a single symbol."""
        response = self._client.get_quote(symbol)
        response.raise_for_status()
        return response.json()

    @_retry_on_transient_error()
    def get_quotes(self, symbols: list[str]) -> dict[str, Any]:
        """Get quotes for multiple symbols."""
        response = self._client.get_quotes(symbols)
        response.raise_for_status()
        return response.json()

    @_retry_on_transient_error()
    def get_price_history_daily(self, symbol: str) -> dict[str, Any]:
        """Get daily price history for a symbol."""
        response = self._client.get_price_history_every_day(symbol)
        response.raise_for_status()
        return response.json()

    @_retry_on_transient_error()
    def get_orders(self, account_hash: str) -> list[dict[str, Any]]:
        """Get orders for an account."""
        response = self._client.get_orders_for_account(account_hash)
        response.raise_for_status()
        return response.json()

    def get_order(self, account_hash: str, order_id: int) -> dict[str, Any] | None:
        """Get a specific order by ID."""
        response = self._client.get_order(order_id, account_hash)
        if response.status_code == 200:
            return response.json()
        return None

    @_retry_on_transient_error()
    def get_transactions(
        self,
        account_hash: str,
        start_date: str | None = None,
        end_date: str | None = None,
        transaction_type: str = "TRADE",
    ) -> list[dict[str, Any]]:
        """Get transactions for an account."""
        from datetime import datetime, timedelta

        end_dt = datetime.fromisoformat(end_date) if end_date else datetime.now()
        start_dt = datetime.fromisoformat(start_date) if start_date else end_dt - timedelta(days=30)

        response = self._client.get_transactions(
            account_hash,
            start_date=start_dt,
            end_date=end_dt,
            transaction_type=self._client.Transactions.TransactionType(transaction_type),
        )
        response.raise_for_status()
        return response.json()

    def _get_account_display_name(self, account_number: str) -> str:
        """Get friendly display name for account."""
        from src.schwab_client.snapshot import get_account_display_name

        return get_account_display_name(account_number)
