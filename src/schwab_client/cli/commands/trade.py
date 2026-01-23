"""
Trade commands: buy, sell, orders.

Implements unified execute_trade() to eliminate duplication between buy/sell.
"""

import os
import sys
from typing import Literal

from config.secure_account_config import secure_config
from src.core.errors import ConfigError, PortfolioError

from ..context import get_client, log_trade_attempt
from ..output import handle_cli_error, print_json_response

# Environment variable names
DEFAULT_ACCOUNT_ENV_VAR = "SCHWAB_DEFAULT_ACCOUNT"
LIVE_TRADES_ENV_VAR = "SCHWAB_ALLOW_LIVE_TRADES"


def resolve_account_alias(account: str | None) -> str:
    """Resolve account alias, using default if not provided."""
    if account:
        return account

    default_account = os.getenv(DEFAULT_ACCOUNT_ENV_VAR)
    if not default_account:
        raise ConfigError(
            f"No account specified and {DEFAULT_ACCOUNT_ENV_VAR} not set. "
            "Either provide an account alias or set the environment variable."
        )
    return default_account


def parse_trade_args(args: list[str], command: str) -> tuple[str, str, int]:
    """Parse [ACCOUNT] SYMBOL QTY, using default account when omitted."""
    if len(args) == 3:
        account, symbol, quantity_raw = args
    elif len(args) == 2:
        account = None
        symbol, quantity_raw = args
    else:
        raise ConfigError(
            f"Usage: schwab {command} [ACCOUNT] SYMBOL QTY "
            f"(set {DEFAULT_ACCOUNT_ENV_VAR} to omit ACCOUNT)."
        )

    account_alias = resolve_account_alias(account)

    try:
        quantity = int(quantity_raw)
    except ValueError as exc:
        raise ConfigError("Quantity must be an integer.") from exc

    return account_alias, symbol.upper(), quantity


def parse_orders_account(args: list[str]) -> str:
    """Parse [ACCOUNT] for orders command with default fallback."""
    if len(args) == 1:
        account = args[0]
    elif len(args) == 0:
        account = None
    else:
        raise ConfigError(
            f"Usage: schwab orders [ACCOUNT] "
            f"(set {DEFAULT_ACCOUNT_ENV_VAR} to omit ACCOUNT)."
        )
    return resolve_account_alias(account)


def is_live_trading_enabled() -> bool:
    """Check if live trading is explicitly enabled via environment variable."""
    value = os.getenv(LIVE_TRADES_ENV_VAR, "").strip().lower()
    return value in ("true", "1", "yes")


def is_interactive_tty() -> bool:
    """Check if we're running in an interactive terminal."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def ensure_trade_confirmation(
    *, output_mode: str, auto_confirm: bool, dry_run: bool, non_interactive: bool
) -> None:
    """Enforce confirmation rules for trade commands.

    SAFETY RULES:
    1. --dry-run is ALWAYS allowed (preview mode)
    2. Live trades require SCHWAB_ALLOW_LIVE_TRADES=true
    3. Live trades require interactive TTY (blocks automation)
    4. Live trades ALWAYS require typing "CONFIRM"
    5. JSON mode can only do --dry-run
    """
    if dry_run:
        return

    if not is_live_trading_enabled():
        raise ConfigError(
            f"Live trading is disabled. Set {LIVE_TRADES_ENV_VAR}=true to enable, "
            "or use --dry-run to preview orders."
        )

    if not is_interactive_tty():
        raise ConfigError(
            "Live trades require an interactive terminal. "
            "Automated/scripted trading is not allowed. Use --dry-run for previews."
        )

    if output_mode == "json":
        raise ConfigError(
            "JSON output mode cannot execute live trades (no interactive confirmation). "
            "Use --dry-run to preview orders in JSON format."
        )

    if non_interactive:
        raise ConfigError(
            "Non-interactive mode cannot execute live trades. "
            "Use --dry-run to preview orders."
        )


def require_trade_confirmation(
    *,
    action: str,
    symbol: str,
    quantity: int,
    account_label: str,
    limit_price: float | None = None,
) -> bool:
    """Require user to type CONFIRM for live trades."""
    print(f"\n{'=' * 60}")
    print("LIVE TRADE CONFIRMATION REQUIRED")
    print(f"{'=' * 60}")
    print(f"Action:   {action}")
    print(f"Symbol:   {symbol}")
    print(f"Quantity: {quantity} shares")
    if limit_price:
        print(f"Type:     LIMIT @ ${limit_price:.2f}")
    else:
        print("Type:     MARKET")
    print(f"Account:  {account_label}")
    print(f"{'=' * 60}")
    print("\nThis will execute a REAL trade with REAL money.")
    print("Type CONFIRM to proceed, or anything else to cancel: ", end="")

    try:
        response = input().strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return False

    return response == "CONFIRM"


def format_order_preview(
    action: str,
    preview: dict,
    limit_price: float | None,
    account_label: str,
    dry_run: bool = False,
) -> str:
    """Format order preview text."""
    header = "ORDER PREVIEW (DRY RUN)" if dry_run else "ORDER PREVIEW"
    lines = [
        f"\n{'=' * 60}",
        header,
        f"{'=' * 60}",
        f"Action:   {action}",
        f"Symbol:   {preview['symbol']}",
        f"Quantity: {preview['quantity']} shares",
    ]
    if limit_price:
        lines.append(f"Type:     LIMIT @ ${limit_price:.2f}")
    else:
        lines.append("Type:     MARKET")
    lines.append(f"Account:  {account_label}")

    if dry_run:
        lines.extend(["", "[DRY RUN - Order not submitted]", ""])

    return "\n".join(lines)


def execute_trade(
    args: list[str],
    *,
    action: Literal["buy", "sell"],
    limit_price: float | None,
    dry_run: bool,
    output_mode: str,
    auto_confirm: bool,
    non_interactive: bool,
) -> None:
    """Execute a trade order (unified buy/sell logic).

    This function handles both buy and sell orders with:
    - Preview generation
    - Safety checks
    - Interactive confirmation
    - Audit logging
    """
    command = action
    action_upper = action.upper()

    try:
        account, symbol, quantity = parse_trade_args(args, command)
        client = get_client()

        account_info = secure_config.get_account_info(account)
        if not account_info:
            raise ConfigError(
                f"Unknown account alias '{account}'. "
                "Use 'schwab accounts' to see available aliases."
            )

        # Generate preview
        if action == "buy":
            if limit_price:
                preview = client.buy_limit(account, symbol, quantity, limit_price, dry_run=True)
            else:
                preview = client.buy_market(account, symbol, quantity, dry_run=True)
        else:  # sell
            if limit_price:
                preview = client.sell_limit(account, symbol, quantity, limit_price, dry_run=True)
            else:
                preview = client.sell_market(account, symbol, quantity, dry_run=True)

        account_label = f"{preview['account']} ({preview['account_number_masked']})"

        # Log attempt
        log_trade_attempt(
            action=action_upper,
            symbol=symbol,
            quantity=quantity,
            account_alias=account,
            limit_price=limit_price,
            dry_run=dry_run,
        )

        # Handle dry run (always allowed)
        if dry_run:
            if output_mode == "json":
                print_json_response(
                    command,
                    data={"preview": preview, "submitted": False, "dry_run": True},
                )
            else:
                print(format_order_preview(action_upper, preview, limit_price, account_label, dry_run=True))
            return

        # Enforce safety rules for live trades
        ensure_trade_confirmation(
            output_mode=output_mode,
            auto_confirm=auto_confirm,
            dry_run=dry_run,
            non_interactive=non_interactive,
        )

        # Show preview
        print(format_order_preview(action_upper, preview, limit_price, account_label))

        # Require explicit confirmation
        confirmed = require_trade_confirmation(
            action=action_upper,
            symbol=symbol,
            quantity=quantity,
            account_label=account_label,
            limit_price=limit_price,
        )

        if not confirmed:
            log_trade_attempt(
                action=action_upper,
                symbol=symbol,
                quantity=quantity,
                account_alias=account,
                limit_price=limit_price,
                cancelled=True,
            )
            print("Order cancelled.")
            return

        # Execute trade
        if action == "buy":
            if limit_price:
                result = client.buy_limit(account, symbol, quantity, limit_price)
            else:
                result = client.buy_market(account, symbol, quantity)
        else:  # sell
            if limit_price:
                result = client.sell_limit(account, symbol, quantity, limit_price)
            else:
                result = client.sell_market(account, symbol, quantity)

        if result.get("success"):
            log_trade_attempt(
                action=action_upper,
                symbol=symbol,
                quantity=quantity,
                account_alias=account,
                limit_price=limit_price,
                executed=True,
            )
            print("\nOrder submitted successfully!")
            print(f"Order ID: {result.get('order_id')}")
        else:
            error_msg = result.get("error", "Unknown error")
            log_trade_attempt(
                action=action_upper,
                symbol=symbol,
                quantity=quantity,
                account_alias=account,
                limit_price=limit_price,
                error=error_msg,
            )
            raise PortfolioError(f"Order failed: {error_msg}")

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_buy(
    args: list[str],
    *,
    limit_price: float | None = None,
    dry_run: bool = False,
    output_mode: str = "text",
    auto_confirm: bool = False,
    non_interactive: bool = False,
) -> None:
    """Execute a buy order."""
    execute_trade(
        args,
        action="buy",
        limit_price=limit_price,
        dry_run=dry_run,
        output_mode=output_mode,
        auto_confirm=auto_confirm,
        non_interactive=non_interactive,
    )


def cmd_sell(
    args: list[str],
    *,
    limit_price: float | None = None,
    dry_run: bool = False,
    output_mode: str = "text",
    auto_confirm: bool = False,
    non_interactive: bool = False,
) -> None:
    """Execute a sell order."""
    execute_trade(
        args,
        action="sell",
        limit_price=limit_price,
        dry_run=dry_run,
        output_mode=output_mode,
        auto_confirm=auto_confirm,
        non_interactive=non_interactive,
    )


def cmd_orders(args: list[str], *, output_mode: str = "text") -> None:
    """Show open orders for an account."""
    command = "orders"
    try:
        account = parse_orders_account(args)
        client = get_client()

        account_number = secure_config.get_account_number(account)
        if not account_number:
            raise ConfigError(f"Unknown account alias '{account}'.")

        account_hash = client.get_account_hash(account_number)
        if not account_hash:
            raise PortfolioError("Could not get account hash.")

        orders = client.get_orders(account_hash)

        account_info = secure_config.get_account_info(account)
        label = account_info.label if account_info else account

        if output_mode == "json":
            print_json_response(
                command,
                data={
                    "account": {
                        "alias": account,
                        "label": label,
                        "account_number_last4": account_number[-4:],
                    },
                    "orders": orders,
                },
            )
            return

        print(f"\n{'=' * 60}")
        print(f"ORDERS - {label}")
        print(f"{'=' * 60}")

        if not orders:
            print("No open orders.")
        else:
            for order in orders:
                status = order.get("status", "UNKNOWN")
                legs = order.get("orderLegCollection", [])

                for leg in legs:
                    instrument = leg.get("instrument", {})
                    symbol = instrument.get("symbol", "???")
                    instruction = leg.get("instruction", "???")
                    qty = leg.get("quantity", 0)
                    price = order.get("price", order.get("stopPrice", "MARKET"))

                    print(f"  {instruction:4s} {qty:>6} {symbol:8s} @ {price}  [{status}]")

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)
