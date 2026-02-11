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
from typing import Any, Literal

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
        return build_performance_report(
            accounts,
            MONEY_MARKET_SYMBOLS,
            self._get_account_display_name,
        )

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

    def get_order(self, account_hash: str, order_id: int) -> dict[str, Any] | None:
        """
        Get a specific order by ID.

        Args:
            account_hash: Account hash from get_account_numbers()
            order_id: Order ID

        Returns:
            Order dict or None if not found
        """
        response = self._client.get_order(order_id, account_hash)
        if response.status_code == 200:
            return response.json()
        return None

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

            # Verify order status - Schwab may accept but then reject asynchronously
            if order_id:
                order_status = self._check_order_status(account_hash, order_id)
                if order_status:
                    return order_status

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

    def _check_order_status(self, account_hash: str, order_id: str) -> dict[str, Any] | None:
        """
        Check if an order was accepted or rejected after submission.

        Schwab may accept an order (201) but then reject it asynchronously.
        This checks the actual order status and returns rejection details.
        """
        try:
            response = self._client.get_order(int(order_id), account_hash)
            if response.status_code == 200:
                order_data = response.json()
                status = order_data.get("status", "UNKNOWN")

                if status == "REJECTED":
                    status_description = order_data.get("statusDescription", "Unknown reason")
                    return {
                        "success": False,
                        "order_id": order_id,
                        "status": "REJECTED",
                        "error": f"Order rejected: {status_description}",
                        "status_description": status_description,
                        "status_code": 201,  # Was accepted but rejected
                    }
                elif status in ("FILLED", "WORKING", "PENDING_ACTIVATION", "QUEUED", "ACCEPTED"):
                    return {
                        "success": True,
                        "order_id": order_id,
                        "status": status,
                        "status_code": 201,
                    }
            return None
        except Exception as e:
            logger.warning(f"Could not verify order status: {e}")
            return None

    def _resolve_account_for_trade(self, account_alias: str) -> dict[str, Any]:
        """Resolve account alias to account details used by order methods."""
        account_number = secure_config.get_account_number(account_alias)
        if not account_number:
            return {"success": False, "error": f"Unknown account alias: {account_alias}"}

        account_hash = self.get_account_hash(account_number)
        if not account_hash:
            return {"success": False, "error": f"Could not get hash for account: {account_alias}"}

        account_info = secure_config.get_account_info(account_alias)
        return {
            "success": True,
            "account_hash": account_hash,
            "account_number": account_number,
            "account_label": account_info.label if account_info else account_alias,
        }

    def _build_equity_order(
        self,
        *,
        action: Literal["BUY", "SELL"],
        order_type: Literal["MARKET", "LIMIT"],
        symbol: str,
        quantity: int,
        limit_price: float | None = None,
    ) -> dict[str, Any]:
        """Build an equity market or limit order payload."""
        symbol_upper = symbol.upper()

        if order_type == "MARKET":
            builder = equity_buy_market if action == "BUY" else equity_sell_market
            return builder(symbol_upper, quantity).build()

        builder = equity_buy_limit if action == "BUY" else equity_sell_limit
        return builder(symbol_upper, quantity, str(limit_price)).build()

    def _submit_equity_order(
        self,
        *,
        account_alias: str,
        symbol: str,
        quantity: int,
        action: Literal["BUY", "SELL"],
        order_type: Literal["MARKET", "LIMIT"],
        limit_price: float | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Build and place/preview an equity order."""
        account = self._resolve_account_for_trade(account_alias)
        if not account.get("success"):
            return {"success": False, "error": account["error"]}

        symbol_upper = symbol.upper()
        order = self._build_equity_order(
            action=action,
            order_type=order_type,
            symbol=symbol_upper,
            quantity=quantity,
            limit_price=limit_price,
        )

        if dry_run:
            preview = {
                "dry_run": True,
                "action": action,
                "order_type": order_type,
                "symbol": symbol_upper,
                "quantity": quantity,
                "account": account["account_label"],
                "account_number_masked": f"...{account['account_number'][-4:]}",
                "order": order,
            }
            if order_type == "LIMIT":
                preview["limit_price"] = limit_price
            return preview

        return self.place_order(account["account_hash"], order)

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
        return self._submit_equity_order(
            account_alias=account_alias,
            symbol=symbol,
            quantity=quantity,
            action="BUY",
            order_type="MARKET",
            dry_run=dry_run,
        )

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
        return self._submit_equity_order(
            account_alias=account_alias,
            symbol=symbol,
            quantity=quantity,
            action="SELL",
            order_type="MARKET",
            dry_run=dry_run,
        )

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
        return self._submit_equity_order(
            account_alias=account_alias,
            symbol=symbol,
            quantity=quantity,
            action="BUY",
            order_type="LIMIT",
            limit_price=limit_price,
            dry_run=dry_run,
        )

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
        return self._submit_equity_order(
            account_alias=account_alias,
            symbol=symbol,
            quantity=quantity,
            action="SELL",
            order_type="LIMIT",
            limit_price=limit_price,
            dry_run=dry_run,
        )

    def cancel_order(self, account_alias: str, order_id: str) -> dict[str, Any]:
        """
        Cancel an existing order.

        Args:
            account_alias: Account alias
            order_id: Order ID to cancel

        Returns:
            Cancellation result
        """
        account = self._resolve_account_for_trade(account_alias)
        if not account.get("success"):
            return {"success": False, "error": account["error"]}

        response = self._client.cancel_order(order_id, account["account_hash"])

        if response.status_code == 200:
            return {"success": True, "order_id": order_id, "status": "cancelled"}
        else:
            return {
                "success": False,
                "error": response.text,
                "status_code": response.status_code,
            }
