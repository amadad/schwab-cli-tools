"""Trading and order-entry methods for the Schwab client wrapper."""

from __future__ import annotations

from typing import Any, Literal

from schwab.orders.equities import (
    equity_buy_limit,
    equity_buy_market,
    equity_sell_limit,
    equity_sell_market,
)

from config.secure_account_config import secure_config

from .common import logger


class TradingClientMixin:
    """Mixin providing order placement and cancellation helpers."""

    def place_order(self, account_hash: str, order: dict) -> dict[str, Any]:
        """Place an order for an account."""
        response = self._client.place_order(account_hash, order)

        if response.status_code == 201:
            location = response.headers.get("Location", "")
            order_id = location.split("/")[-1] if location else None

            if order_id:
                order_status = self._check_order_status(account_hash, order_id)
                if order_status:
                    return order_status

            return {
                "success": True,
                "order_id": order_id,
                "status_code": response.status_code,
            }

        return {
            "success": False,
            "error": response.text,
            "status_code": response.status_code,
        }

    def _check_order_status(self, account_hash: str, order_id: str) -> dict[str, Any] | None:
        """Check whether an accepted order was later rejected asynchronously."""
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
                        "status_code": 201,
                    }
                if status in {"FILLED", "WORKING", "PENDING_ACTIVATION", "QUEUED", "ACCEPTED"}:
                    return {
                        "success": True,
                        "order_id": order_id,
                        "status": status,
                        "status_code": 201,
                    }
            return None
        except Exception as exc:  # pragma: no cover - defensive logging path
            logger.warning("Could not verify order status: %s", exc)
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
        order_type: Literal["MARKET", "LIMIT", "STOP", "STOP_LIMIT", "TRAILING_STOP"],
        symbol: str,
        quantity: int,
        limit_price: float | None = None,
        stop_price: float | None = None,
        trailing_stop_percent: float | None = None,
    ) -> dict[str, Any]:
        """Build an equity order payload."""
        symbol_upper = symbol.upper()
        instruction = "BUY" if action == "BUY" else "SELL"

        if order_type == "MARKET":
            builder = equity_buy_market if action == "BUY" else equity_sell_market
            return builder(symbol_upper, quantity).build()

        if order_type == "LIMIT":
            builder = equity_buy_limit if action == "BUY" else equity_sell_limit
            return builder(symbol_upper, quantity, str(limit_price)).build()

        order: dict[str, Any] = {
            "orderStrategyType": "SINGLE",
            "session": "NORMAL",
            "duration": "GOOD_TILL_CANCEL",
            "orderLegCollection": [
                {
                    "instruction": instruction,
                    "quantity": quantity,
                    "instrument": {
                        "symbol": symbol_upper,
                        "assetType": "EQUITY",
                    },
                }
            ],
        }

        if order_type == "STOP":
            order["orderType"] = "STOP"
            order["stopPrice"] = str(stop_price)
        elif order_type == "STOP_LIMIT":
            order["orderType"] = "STOP_LIMIT"
            order["stopPrice"] = str(stop_price)
            order["price"] = str(limit_price)
        elif order_type == "TRAILING_STOP":
            order["orderType"] = "TRAILING_STOP"
            order["stopPriceLinkBasis"] = "MARK"
            order["stopPriceLinkType"] = "PERCENT"
            order["stopPriceOffset"] = str(trailing_stop_percent)

        return order

    def _submit_equity_order(
        self,
        *,
        account_alias: str,
        symbol: str,
        quantity: int,
        action: Literal["BUY", "SELL"],
        order_type: Literal["MARKET", "LIMIT", "STOP", "STOP_LIMIT", "TRAILING_STOP"],
        limit_price: float | None = None,
        stop_price: float | None = None,
        trailing_stop_percent: float | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Build and place or preview an equity order."""
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
            stop_price=stop_price,
            trailing_stop_percent=trailing_stop_percent,
        )

        if dry_run:
            preview: dict[str, Any] = {
                "dry_run": True,
                "action": action,
                "order_type": order_type,
                "symbol": symbol_upper,
                "quantity": quantity,
                "account": account["account_label"],
                "account_number_masked": f"...{account['account_number'][-4:]}",
                "order": order,
            }
            if limit_price is not None:
                preview["limit_price"] = limit_price
            if stop_price is not None:
                preview["stop_price"] = stop_price
            if trailing_stop_percent is not None:
                preview["trailing_stop_percent"] = trailing_stop_percent
            return preview

        return self.place_order(account["account_hash"], order)

    def buy_market(
        self,
        account_alias: str,
        symbol: str,
        quantity: int,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Place a market buy order."""
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
        """Place a market sell order."""
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
        """Place a limit buy order."""
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
        """Place a limit sell order."""
        return self._submit_equity_order(
            account_alias=account_alias,
            symbol=symbol,
            quantity=quantity,
            action="SELL",
            order_type="LIMIT",
            limit_price=limit_price,
            dry_run=dry_run,
        )

    def sell_stop(
        self,
        account_alias: str,
        symbol: str,
        quantity: int,
        stop_price: float,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Place a stop sell order."""
        return self._submit_equity_order(
            account_alias=account_alias,
            symbol=symbol,
            quantity=quantity,
            action="SELL",
            order_type="STOP",
            stop_price=stop_price,
            dry_run=dry_run,
        )

    def sell_stop_limit(
        self,
        account_alias: str,
        symbol: str,
        quantity: int,
        stop_price: float,
        limit_price: float,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Place a stop-limit sell order."""
        return self._submit_equity_order(
            account_alias=account_alias,
            symbol=symbol,
            quantity=quantity,
            action="SELL",
            order_type="STOP_LIMIT",
            stop_price=stop_price,
            limit_price=limit_price,
            dry_run=dry_run,
        )

    def sell_trailing_stop(
        self,
        account_alias: str,
        symbol: str,
        quantity: int,
        trailing_stop_percent: float,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Place a trailing stop sell order."""
        return self._submit_equity_order(
            account_alias=account_alias,
            symbol=symbol,
            quantity=quantity,
            action="SELL",
            order_type="TRAILING_STOP",
            trailing_stop_percent=trailing_stop_percent,
            dry_run=dry_run,
        )

    def cancel_order(self, account_alias: str, order_id: str) -> dict[str, Any]:
        """Cancel an existing order."""
        account = self._resolve_account_for_trade(account_alias)
        if not account.get("success"):
            return {"success": False, "error": account["error"]}

        response = self._client.cancel_order(order_id, account["account_hash"])
        if response.status_code == 200:
            return {"success": True, "order_id": order_id, "status": "cancelled"}
        return {
            "success": False,
            "error": response.text,
            "status_code": response.status_code,
        }
