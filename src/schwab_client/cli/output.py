"""
Output formatting utilities for CLI.

Provides:
- JSON envelope builder
- Text formatters
- @command decorator for reducing boilerplate
- Optional rich terminal output (if rich is installed)
"""

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import Any, Callable, TypeVar

import httpx

from src.core.errors import ConfigError, PortfolioError

SCHEMA_VERSION = 1

# Optional rich support
try:
    from rich.console import Console
    from rich.json import JSON as RichJSON
    from rich.table import Table
    from rich.panel import Panel
    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None

F = TypeVar("F", bound=Callable[..., Any])


def build_response(
    command: str,
    *,
    success: bool = True,
    data: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build standardized JSON response envelope."""
    return {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "success": success,
        "data": data,
        "error": error,
    }


def print_json_response(
    command: str,
    *,
    success: bool = True,
    data: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    """Print JSON response to stdout."""
    response = build_response(command, success=success, data=data, error=error)
    print(json.dumps(response, indent=2, default=str))


def print_error_json(command: str, error_type: str, message: str) -> None:
    """Print JSON error response."""
    print_json_response(
        command,
        success=False,
        error={"type": error_type, "message": message},
    )


def handle_cli_error(error: Exception, *, output_mode: str, command: str) -> None:
    """Centralized error handling for CLI commands.

    Maps exceptions to appropriate exit codes:
    - 1: User/config errors (ConfigError, PortfolioError)
    - 2: API/HTTP errors
    """
    if isinstance(error, ConfigError):
        if output_mode == "json":
            print_error_json(command, "ConfigError", str(error))
        else:
            print(f"Configuration error: {error}", file=sys.stderr)
        sys.exit(1)

    elif isinstance(error, PortfolioError):
        if output_mode == "json":
            print_error_json(command, "PortfolioError", str(error))
        else:
            print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    elif isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code if error.response else None
        message = f"API request failed (status {status_code or 'unknown'})."

        if status_code == 401:
            message += " Token may have expired. Run 'schwab-auth' to re-authenticate."
        elif status_code == 403:
            message += " Access denied. Check API permissions."

        if output_mode == "json":
            print_error_json(command, "APIError", message)
        else:
            print(f"API Error: {message}", file=sys.stderr)
        sys.exit(2)

    else:
        if output_mode == "json":
            print_error_json(command, "UnexpectedError", str(error))
        else:
            print(f"Unexpected error: {error}", file=sys.stderr)
        sys.exit(1)


@dataclass
class CommandResult:
    """Result from a command handler."""
    data: dict[str, Any]
    text_output: str | None = None


def command(name: str):
    """Decorator that handles common command boilerplate.

    Wraps command function with:
    - Error handling (try/except with proper exit codes)
    - JSON/text output branching
    - Response envelope for JSON mode

    Usage:
        @command("portfolio")
        def cmd_portfolio(ctx: CommandContext) -> CommandResult:
            data = ctx.client.get_portfolio_summary()
            text = format_portfolio_text(data)
            return CommandResult(data=data, text_output=text)
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, output_mode: str = "text", **kwargs):
            try:
                result = func(*args, output_mode=output_mode, **kwargs)

                if isinstance(result, CommandResult):
                    if output_mode == "json":
                        print_json_response(name, data=result.data)
                    elif result.text_output:
                        print(result.text_output)
                # If function handles output itself, do nothing
                return result

            except Exception as exc:
                handle_cli_error(exc, output_mode=output_mode, command=name)

        return wrapper  # type: ignore
    return decorator


def format_header(title: str, width: int = 60) -> str:
    """Format a section header."""
    return f"\n{'=' * width}\n{title}\n{'=' * width}"


def format_table_row(label: str, value: Any, width: int = 20) -> str:
    """Format a label-value row."""
    return f"  {label:<{width}} {value}"


def format_currency(value: float | None, prefix: str = "$") -> str:
    """Format a currency value."""
    if value is None:
        return "N/A"
    return f"{prefix}{value:,.2f}"


def format_percent(value: float | None, decimals: int = 2) -> str:
    """Format a percentage value."""
    if value is None:
        return "N/A"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def format_change(value: float | None, is_percent: bool = False) -> str:
    """Format a change value with sign."""
    if value is None:
        return "N/A"
    sign = "+" if value > 0 else ""
    if is_percent:
        return f"{sign}{value:.2f}%"
    return f"{sign}${value:,.2f}"


# =============================================================================
# Rich Terminal Output (optional enhancement)
# =============================================================================

def print_rich_json(data: dict[str, Any]) -> None:
    """Print JSON with syntax highlighting using rich (if available)."""
    if RICH_AVAILABLE and console:
        console.print(RichJSON(json.dumps(data, indent=2, default=str)))
    else:
        print(json.dumps(data, indent=2, default=str))


def print_rich_header(title: str, subtitle: str | None = None) -> None:
    """Print a styled header using rich (if available)."""
    if RICH_AVAILABLE and console:
        if subtitle:
            console.print(Panel(f"[bold]{title}[/bold]\n{subtitle}", expand=False))
        else:
            console.print(Panel(f"[bold]{title}[/bold]", expand=False))
    else:
        print(format_header(title))
        if subtitle:
            print(f"  {subtitle}")


def create_positions_table(positions: list[dict[str, Any]]) -> str:
    """Create a formatted positions table.

    Uses rich Table if available, otherwise returns plain text.
    """
    if not positions:
        return "  No positions found."

    if RICH_AVAILABLE:
        table = Table(title="Positions")
        table.add_column("Symbol", style="cyan", no_wrap=True)
        table.add_column("Shares", justify="right")
        table.add_column("Value", justify="right", style="green")
        table.add_column("Change", justify="right")
        table.add_column("Account")

        for pos in positions:
            change = pos.get("day_gain_percent", 0)
            change_style = "green" if change >= 0 else "red"
            change_str = f"+{change:.2f}%" if change >= 0 else f"{change:.2f}%"

            table.add_row(
                pos.get("symbol", "???"),
                f"{pos.get('quantity', 0):.2f}",
                format_currency(pos.get("market_value", 0)),
                f"[{change_style}]{change_str}[/{change_style}]",
                pos.get("account_name", ""),
            )

        # Render to string
        import io
        from rich.console import Console as RichConsole
        buf = io.StringIO()
        temp_console = RichConsole(file=buf, force_terminal=True)
        temp_console.print(table)
        return buf.getvalue()

    # Plain text fallback
    lines = []
    for pos in positions:
        symbol = pos.get("symbol", "???")
        qty = pos.get("quantity", 0)
        value = pos.get("market_value", 0)
        change = pos.get("day_gain_percent", 0)
        account = pos.get("account_name", "")
        sign = "+" if change >= 0 else ""
        lines.append(
            f"  {symbol:8s} {qty:>8.2f} {format_currency(value):>14s}  {sign}{change:.2f}%  [{account}]"
        )
    return "\n".join(lines)


def format_value_with_change(
    value: float,
    change: float | None = None,
    change_pct: float | None = None,
) -> str:
    """Format a value with optional change indicator."""
    result = format_currency(value)
    if change is not None and change_pct is not None:
        sign = "+" if change >= 0 else ""
        result += f" ({sign}{change_pct:.2f}%)"
    return result
