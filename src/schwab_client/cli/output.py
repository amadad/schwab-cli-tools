"""
Output formatting utilities for CLI.

Provides:
- JSON envelope builder
- Text formatters
- Centralized error handling
"""

import json
import sys
from datetime import datetime
from typing import Any

import httpx

from config.secure_account_config import secure_config
from src.core.errors import ConfigError, PortfolioError

SCHEMA_VERSION = 1


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


def scrub_account_identifiers(data: Any) -> Any:
    """Recursively replace account numbers with aliases in output data.

    Prevents accidental exposure of account numbers in JSON output
    that may be logged or shared by agents.
    """
    if not secure_config.account_mappings:
        return data

    # Build reverse map: account_number -> alias
    number_to_alias = {v: k for k, v in secure_config.account_mappings.items()}

    return _scrub_recursive(data, number_to_alias)


def _scrub_recursive(data: Any, number_to_alias: dict[str, str]) -> Any:
    """Recursively scrub account numbers from data structures."""
    if isinstance(data, str):
        for number, alias in number_to_alias.items():
            if number in data:
                data = data.replace(number, f"[{alias}]")
        return data
    elif isinstance(data, dict):
        return {k: _scrub_recursive(v, number_to_alias) for k, v in data.items()}
    elif isinstance(data, list):
        return [_scrub_recursive(item, number_to_alias) for item in data]
    return data


def print_json_response(
    command: str,
    *,
    success: bool = True,
    data: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    """Print JSON response to stdout."""
    response = build_response(command, success=success, data=data, error=error)
    response = scrub_account_identifiers(response)
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

        # Extract Schwab correlation ID for support tickets
        request_id = None
        if error.response is not None:
            request_id = (
                error.response.headers.get("Schwab-Client-CorrelId")
                or error.response.headers.get("X-Request-Id")
                or error.response.headers.get("X-Correlation-Id")
            )

        if output_mode == "json":
            error_data = {"type": "APIError", "message": message}
            if request_id:
                error_data["request_id"] = request_id
            if status_code:
                error_data["status_code"] = status_code
            print_json_response(command, success=False, error=error_data)
        else:
            print(f"API Error: {message}", file=sys.stderr)
            if request_id:
                print(
                    f"  Request ID: {request_id} (reference this in support tickets)",
                    file=sys.stderr,
                )
        sys.exit(2)

    else:
        if output_mode == "json":
            print_error_json(command, "UnexpectedError", str(error))
        else:
            print(f"Unexpected error: {error}", file=sys.stderr)
        sys.exit(1)


def format_header(title: str, width: int = 60) -> str:
    """Format a section header."""
    return f"\n{'=' * width}\n{title}\n{'=' * width}"


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
