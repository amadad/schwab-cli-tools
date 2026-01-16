"""
Enhanced Schwab client wrapper with project-specific features.

Wraps the official schwab-py client to provide:
- Account label resolution from secure config
- Money market fund detection (treated as cash)
- Portfolio aggregation utilities
- Order placement with safety checks
- Consistent error handling
"""

import logging
from typing import Any

from schwab.orders.equities import (
    equity_buy_limit,
    equity_buy_market,
    equity_sell_limit,
    equity_sell_market,
)

from config.secure_account_config import secure_config
from src.core.portfolio_service import (
    analyze_allocation,
    build_account_balances,
    build_performance_report,
    build_portfolio_summary,
    build_positions,
)

logger = logging.getLogger(__name__)

# Money market fund symbols treated as cash equivalents
MONEY_MARKET_SYMBOLS = frozenset({"SWGXX", "SWVXX", "SNOXX", "SNSXX", "SNVXX"})


class SchwabClientWrapper:
    """
    Wrapper around official schwab-py client with project enhancements.

    Features:
    - Account label resolution from config
    - Money market detection (counts as cash)
    - Portfolio summary aggregation
    - Structured error handling

    Usage:
        from src.schwab_client import get_authenticated_client, SchwabClientWrapper

        raw_client = get_authenticated_client()
        client = SchwabClientWrapper(raw_client)

        summary = client.get_portfolio_summary()
        print(f"Total value: ${summary['total_value']:,.2f}")
    """

    def __init__(self, client):
        """
        Initialize wrapper with authenticated schwab.Client.

        Args:
            client: Authenticated schwab.Client from schwab-py
        """
        self._client = client
        self._account_hashes: dict[str, str] | None = None

    @property
    def raw_client(self):
        """Access underlying schwab-py client for advanced operations"""
        return self._client

    def get_account_numbers(self) -> list[dict[str, str]]:
        """
        Get account numbers with hash values.

        The hash values are required for most account-specific API calls.

        Returns:
            List of dicts with 'accountNumber' and 'hashValue'
        """
        response = self._client.get_account_numbers()
        response.raise_for_status()
        accounts = response.json()

        # Cache hash values for later use
        self._account_hashes = {acc["accountNumber"]: acc["hashValue"] for acc in accounts}

        return accounts

    def get_account_hash(self, account_number: str) -> str | None:
        """
        Get hash value for an account number.

        Args:
            account_number: Plain account number

        Returns:
            Hash value for API calls, or None if not found
        """
        if self._account_hashes is None:
            self.get_account_numbers()
        return self._account_hashes.get(account_number) if self._account_hashes else None

    def get_account(self, account_hash: str, include_positions: bool = True) -> dict[str, Any]:
        """
        Get account details by hash value.

        Args:
            account_hash: Account hash from get_account_numbers()
            include_positions: Whether to include position data

        Returns:
            Account data dict with balances and optionally positions
        """
        if include_positions:
            response = self._client.get_account(
                account_hash, fields=self._client.Account.Fields.POSITIONS
            )
        else:
            response = self._client.get_account(account_hash)

        response.raise_for_status()
        return response.json()

    def get_all_accounts_full(self) -> list[dict[str, Any]]:
        """
        Get all accounts with positions.

        Returns:
            List of account data dicts with positions
        """
        response = self._client.get_accounts(fields=self._client.Account.Fields.POSITIONS)
        response.raise_for_status()
        return response.json()

    def get_portfolio_summary(self) -> dict[str, Any]:
        """
        Get comprehensive portfolio summary with cash/invested breakdown.

        Handles money market funds as cash equivalents.

        Returns:
            Dict with:
            - total_value: Total portfolio value
            - total_cash: Cash + money market funds
            - total_invested: Value in securities
            - cash_percentage: Cash as % of portfolio
            - account_count: Number of accounts
            - position_count: Number of positions
            - positions: List of position dicts
        """
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

    def get_portfolio_performance(self) -> dict[str, Any]:
        """Get portfolio performance metrics."""
        accounts = self.get_all_accounts_full()
        return build_performance_report(accounts, MONEY_MARKET_SYMBOLS)

    def get_quote(self, symbol: str) -> dict[str, Any]:
        """
        Get quote for a single symbol.

        Args:
            symbol: Stock/ETF symbol

        Returns:
            Quote data dict
        """
        response = self._client.get_quote(symbol)
        response.raise_for_status()
        return response.json()

    def get_quotes(self, symbols: list[str]) -> dict[str, Any]:
        """
        Get quotes for multiple symbols.

        Args:
            symbols: List of stock/ETF symbols

        Returns:
            Dict mapping symbols to quote data
        """
        response = self._client.get_quotes(symbols)
        response.raise_for_status()
        return response.json()

    def get_price_history_daily(self, symbol: str) -> dict[str, Any]:
        """
        Get daily price history for a symbol.

        Args:
            symbol: Stock/ETF symbol

        Returns:
            Price history with candles
        """
        response = self._client.get_price_history_every_day(symbol)
        response.raise_for_status()
        return response.json()

    def get_orders(self, account_hash: str) -> list[dict[str, Any]]:
        """
        Get orders for an account.

        Args:
            account_hash: Account hash from get_account_numbers()

        Returns:
            List of order dicts
        """
        response = self._client.get_orders_for_account(account_hash)
        response.raise_for_status()
        return response.json()

    def get_transactions(
        self,
        account_hash: str,
        start_date: str | None = None,
        end_date: str | None = None,
        transaction_type: str = "TRADE",
    ) -> list[dict[str, Any]]:
        """
        Get transactions for an account.

        Args:
            account_hash: Account hash from get_account_numbers()
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            transaction_type: Type filter (TRADE, DIVIDEND_OR_INTEREST, etc.)

        Returns:
            List of transaction dicts
        """
        from datetime import datetime, timedelta

        # Default to last 30 days
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
        """Get friendly display name for account"""
        label = secure_config.get_account_label(account_number)
        if label:
            return label
        # Fallback to masked number
        if len(account_number) > 4:
            return f"Account (...{account_number[-4:]})"
        return f"Account ({account_number})"

    # ==================== ORDER PLACEMENT ====================

    def place_order(self, account_hash: str, order: dict) -> dict[str, Any]:
        """
        Place an order for an account.

        Args:
            account_hash: Account hash from get_account_numbers()
            order: Order object from schwab.orders builders

        Returns:
            Dict with order_id and status
        """
        response = self._client.place_order(account_hash, order)

        # Schwab returns 201 Created with Location header containing order ID
        if response.status_code == 201:
            location = response.headers.get("Location", "")
            # Extract order ID from location URL
            order_id = location.split("/")[-1] if location else None
            return {
                "success": True,
                "order_id": order_id,
                "status_code": response.status_code,
            }
        else:
            return {
                "success": False,
                "error": response.text,
                "status_code": response.status_code,
            }

    def buy_market(
        self,
        account_alias: str,
        symbol: str,
        quantity: int,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Place a market buy order.

        Args:
            account_alias: Account alias (e.g., 'acct_trading')
            symbol: Stock/ETF symbol
            quantity: Number of shares
            dry_run: If True, return order preview without executing

        Returns:
            Order result or preview
        """
        # Resolve account
        account_number = secure_config.get_account_number(account_alias)
        if not account_number:
            return {"success": False, "error": f"Unknown account alias: {account_alias}"}

        account_hash = self.get_account_hash(account_number)
        if not account_hash:
            return {"success": False, "error": f"Could not get hash for account: {account_alias}"}

        account_info = secure_config.get_account_info(account_alias)

        # Build order
        order = equity_buy_market(symbol.upper(), quantity).build()

        if dry_run:
            return {
                "dry_run": True,
                "action": "BUY",
                "order_type": "MARKET",
                "symbol": symbol.upper(),
                "quantity": quantity,
                "account": account_info.label if account_info else account_alias,
                "account_number_masked": f"...{account_number[-4:]}",
                "order": order,
            }

        return self.place_order(account_hash, order)

    def sell_market(
        self,
        account_alias: str,
        symbol: str,
        quantity: int,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Place a market sell order.

        Args:
            account_alias: Account alias (e.g., 'acct_trading')
            symbol: Stock/ETF symbol
            quantity: Number of shares
            dry_run: If True, return order preview without executing

        Returns:
            Order result or preview
        """
        # Resolve account
        account_number = secure_config.get_account_number(account_alias)
        if not account_number:
            return {"success": False, "error": f"Unknown account alias: {account_alias}"}

        account_hash = self.get_account_hash(account_number)
        if not account_hash:
            return {"success": False, "error": f"Could not get hash for account: {account_alias}"}

        account_info = secure_config.get_account_info(account_alias)

        # Build order
        order = equity_sell_market(symbol.upper(), quantity).build()

        if dry_run:
            return {
                "dry_run": True,
                "action": "SELL",
                "order_type": "MARKET",
                "symbol": symbol.upper(),
                "quantity": quantity,
                "account": account_info.label if account_info else account_alias,
                "account_number_masked": f"...{account_number[-4:]}",
                "order": order,
            }

        return self.place_order(account_hash, order)

    def buy_limit(
        self,
        account_alias: str,
        symbol: str,
        quantity: int,
        limit_price: float,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Place a limit buy order.

        Args:
            account_alias: Account alias (e.g., 'acct_trading')
            symbol: Stock/ETF symbol
            quantity: Number of shares
            limit_price: Maximum price to pay
            dry_run: If True, return order preview without executing

        Returns:
            Order result or preview
        """
        # Resolve account
        account_number = secure_config.get_account_number(account_alias)
        if not account_number:
            return {"success": False, "error": f"Unknown account alias: {account_alias}"}

        account_hash = self.get_account_hash(account_number)
        if not account_hash:
            return {"success": False, "error": f"Could not get hash for account: {account_alias}"}

        account_info = secure_config.get_account_info(account_alias)

        # Build order (price as string to avoid deprecation warning)
        order = equity_buy_limit(symbol.upper(), quantity, str(limit_price)).build()

        if dry_run:
            return {
                "dry_run": True,
                "action": "BUY",
                "order_type": "LIMIT",
                "symbol": symbol.upper(),
                "quantity": quantity,
                "limit_price": limit_price,
                "account": account_info.label if account_info else account_alias,
                "account_number_masked": f"...{account_number[-4:]}",
                "order": order,
            }

        return self.place_order(account_hash, order)

    def sell_limit(
        self,
        account_alias: str,
        symbol: str,
        quantity: int,
        limit_price: float,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Place a limit sell order.

        Args:
            account_alias: Account alias (e.g., 'acct_trading')
            symbol: Stock/ETF symbol
            quantity: Number of shares
            limit_price: Minimum price to accept
            dry_run: If True, return order preview without executing

        Returns:
            Order result or preview
        """
        # Resolve account
        account_number = secure_config.get_account_number(account_alias)
        if not account_number:
            return {"success": False, "error": f"Unknown account alias: {account_alias}"}

        account_hash = self.get_account_hash(account_number)
        if not account_hash:
            return {"success": False, "error": f"Could not get hash for account: {account_alias}"}

        account_info = secure_config.get_account_info(account_alias)

        # Build order (price as string to avoid deprecation warning)
        order = equity_sell_limit(symbol.upper(), quantity, str(limit_price)).build()

        if dry_run:
            return {
                "dry_run": True,
                "action": "SELL",
                "order_type": "LIMIT",
                "symbol": symbol.upper(),
                "quantity": quantity,
                "limit_price": limit_price,
                "account": account_info.label if account_info else account_alias,
                "account_number_masked": f"...{account_number[-4:]}",
                "order": order,
            }

        return self.place_order(account_hash, order)

    def cancel_order(self, account_alias: str, order_id: str) -> dict[str, Any]:
        """
        Cancel an existing order.

        Args:
            account_alias: Account alias
            order_id: Order ID to cancel

        Returns:
            Cancellation result
        """
        account_number = secure_config.get_account_number(account_alias)
        if not account_number:
            return {"success": False, "error": f"Unknown account alias: {account_alias}"}

        account_hash = self.get_account_hash(account_number)
        if not account_hash:
            return {"success": False, "error": f"Could not get hash for account: {account_alias}"}

        response = self._client.cancel_order(order_id, account_hash)

        if response.status_code == 200:
            return {"success": True, "order_id": order_id, "status": "cancelled"}
        else:
            return {
                "success": False,
                "error": response.text,
                "status_code": response.status_code,
            }
