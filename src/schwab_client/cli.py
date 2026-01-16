"""
CLI for Schwab portfolio management

Usage:
    schwab portfolio [-p] [--json|--text]      Show portfolio summary (with positions)
    schwab positions [--symbol SYMBOL]        Show positions (optional filter)
    schwab balance [--json|--text]            Show account balances
    schwab allocation [--json|--text]         Analyze allocation and concentration
    schwab performance [--json|--text]        Show daily performance metrics
    schwab vix [--json|--text]                Show VIX data
    schwab indices [--json|--text]            Show major index quotes
    schwab sectors [--json|--text]            Show sector performance
    schwab market [--json|--text]             Show aggregated market signals
    schwab auth [--json|--text]               Check authentication status
    schwab doctor [--json|--text]             Run diagnostics for auth/config
    schwab report [--output PATH] [--no-market] [--json|--text]
    schwab buy [ACCOUNT] SYMBOL QTY [--limit PRICE] [--dry-run] [--yes]
    schwab sell [ACCOUNT] SYMBOL QTY [--limit PRICE] [--dry-run] [--yes]
    schwab orders [ACCOUNT]                   Show open orders
    schwab accounts [--json|--text]           List available account aliases
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from config.secure_account_config import ACCOUNTS_FILE, secure_config
from src.core.errors import ConfigError, PortfolioError
from src.core.market_service import (
    get_market_indices,
    get_market_signals,
    get_sector_performance,
    get_vix,
)
from src.core.portfolio_service import (
    analyze_allocation,
    build_account_balances,
    build_performance_report,
    build_portfolio_summary,
)

from .auth import TokenManager, get_authenticated_client, resolve_data_dir, resolve_token_path
from .client import MONEY_MARKET_SYMBOLS, SchwabClientWrapper
from .market_auth import get_market_client, resolve_market_token_path

SCHEMA_VERSION = 1
OUTPUT_ENV_VAR = "SCHWAB_OUTPUT"
DEFAULT_ACCOUNT_ENV_VAR = "SCHWAB_DEFAULT_ACCOUNT"
REPORT_DIR_ENV_VAR = "SCHWAB_REPORT_DIR"


def build_response(
    command: str,
    *,
    data: Any | None = None,
    success: bool = True,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a consistent JSON response envelope."""
    return {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "timestamp": datetime.now().isoformat(),
        "success": success,
        "data": data,
        "error": error,
    }


def print_json_response(
    command: str,
    *,
    data: Any | None = None,
    success: bool = True,
    error: dict[str, Any] | None = None,
) -> None:
    """Print a JSON response envelope."""
    payload = build_response(command, data=data, success=success, error=error)
    print(json.dumps(payload, indent=2))


def resolve_output_mode(parsed_args: argparse.Namespace) -> str:
    """Resolve output mode based on CLI args and environment defaults."""
    env_value = os.getenv(OUTPUT_ENV_VAR, "").strip().lower()
    default_mode = "json" if env_value == "json" else "text"

    if parsed_args.json:
        return "json"
    if parsed_args.text:
        return "text"
    return default_mode


def resolve_account_alias(account: str | None) -> str:
    """Resolve account alias from argument or environment default."""
    if account:
        return account
    default_account = os.getenv(DEFAULT_ACCOUNT_ENV_VAR)
    if default_account:
        return default_account
    raise ConfigError(
        f"Missing account alias. Provide ACCOUNT or set {DEFAULT_ACCOUNT_ENV_VAR}."
    )


def resolve_market_client():
    """Get a market data client with helpful errors."""
    try:
        return get_market_client()
    except Exception as exc:
        raise ConfigError(
            "Market data not authenticated. Run 'schwab-market-auth' to authenticate."
        ) from exc


def resolve_report_dir() -> Path:
    """Resolve the directory where reports are stored."""
    env_dir = os.getenv(REPORT_DIR_ENV_VAR)
    if env_dir:
        return Path(env_dir).expanduser()
    return resolve_data_dir() / "reports"


def resolve_report_path(output_path: str | None, *, timestamp: datetime | None = None) -> Path:
    """Resolve the report output path, defaulting to the report directory."""
    if output_path:
        path = Path(output_path).expanduser()
    else:
        ts = timestamp or datetime.now()
        path = resolve_report_dir() / f"report-{ts.strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _account_display_name(account_number: str) -> str:
    label = secure_config.get_account_label(account_number)
    if label:
        return label
    if len(account_number) > 4:
        return f"Account (...{account_number[-4:]})"
    return f"Account ({account_number})"


def _sanitize_summary_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for pos in positions:
        entry = dict(pos)
        account_number = entry.pop("account_number", None)
        if account_number:
            entry["account_number_masked"] = secure_config.mask_account_number(
                str(account_number)
            )
            entry["account_number_last4"] = str(account_number)[-4:]
        sanitized.append(entry)
    return sanitized


def parse_trade_args(args: list[str], command: str) -> tuple[str, str, int]:
    """Parse [ACCOUNT] SYMBOL QTY, using default account when omitted."""
    if len(args) == 3:
        account, symbol, quantity_raw = args
    elif len(args) == 2:
        account = None
        symbol, quantity_raw = args
    else:
        raise ConfigError(
            f"Usage: schwab {command} [ACCOUNT] SYMBOL QTY (set {DEFAULT_ACCOUNT_ENV_VAR} to omit ACCOUNT)."
        )

    account_alias = resolve_account_alias(account)

    try:
        quantity = int(quantity_raw)
    except ValueError as exc:
        raise ConfigError("Quantity must be an integer.") from exc

    return account_alias, symbol, quantity


def parse_orders_account(args: list[str]) -> str:
    """Parse [ACCOUNT] for orders command with default fallback."""
    if len(args) == 1:
        account = args[0]
    elif len(args) == 0:
        account = None
    else:
        raise ConfigError(
            f"Usage: schwab orders [ACCOUNT] (set {DEFAULT_ACCOUNT_ENV_VAR} to omit ACCOUNT)."
        )
    return resolve_account_alias(account)


def ensure_trade_confirmation(
    *, output_mode: str, auto_confirm: bool, dry_run: bool, non_interactive: bool
) -> None:
    """Enforce confirmation rules for trade commands."""
    if output_mode == "json" and not (auto_confirm or dry_run):
        raise ConfigError("JSON output requires --yes or --dry-run for trade commands.")
    if non_interactive and not (auto_confirm or dry_run):
        raise ConfigError("Non-interactive mode requires --yes or --dry-run for trade commands.")


def handle_cli_error(error: Exception, *, output_mode: str, command: str) -> None:
    """Handle CLI errors consistently."""
    status_code = None
    exit_code = 1

    if isinstance(error, PortfolioError):
        message = str(error)
    elif isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code if error.response else None
        message = f"API request failed (status {status_code if status_code else 'unknown'})."
        exit_code = 2
    else:
        message = f"Unexpected error: {error}"

    if output_mode == "json":
        error_payload = {
            "message": message,
            "type": error.__class__.__name__,
        }
        if status_code is not None:
            error_payload["status_code"] = status_code
        print_json_response(command, success=False, error=error_payload)
    else:
        print(message, file=sys.stderr)

    sys.exit(exit_code)


def print_portfolio(*, include_positions: bool, output_mode: str) -> None:
    """Print portfolio summary."""
    command = "portfolio"
    try:
        raw_client = get_authenticated_client()
        client = SchwabClientWrapper(raw_client)
        summary = client.get_portfolio_summary()

        if output_mode == "json":
            summary_payload = dict(summary)
            if not include_positions:
                summary_payload["positions"] = []
            print_json_response(command, data={"summary": summary_payload})
            return

        print(f"\n{'=' * 60}")
        print("PORTFOLIO SUMMARY")
        print(f"{'=' * 60}")
        print(f"Total Value:    ${summary['total_value']:,.2f}")
        print(f"Total Cash:     ${summary['total_cash']:,.2f}")
        print(f"Total Invested: ${summary['total_invested']:,.2f}")
        print(f"Accounts:       {summary['account_count']}")
        print(f"Positions:      {summary['position_count']}")

        if summary["total_invested"] > 0:
            total_gain = summary["total_unrealized_pl"]
            total_pct = (total_gain / summary["total_invested"]) * 100
            print(f"Unrealized P&L: ${total_gain:+,.2f} ({total_pct:+.2f}%)")

        if include_positions and summary["positions"]:
            print(f"\n{'=' * 60}")
            print("POSITIONS")
            print(f"{'=' * 60}")

            # Sort by value
            positions = sorted(
                summary["positions"], key=lambda p: p.get("market_value", 0), reverse=True
            )

            for pos in positions:
                symbol = pos.get("symbol", "Unknown")
                value = pos.get("market_value", 0)
                pct = (
                    (value / summary["total_value"] * 100)
                    if summary["total_value"] > 0
                    else 0
                )
                pnl = pos.get("unrealized_pl", 0)
                print(
                    f"  {symbol:8s} ${value:>12,.2f} ({pct:5.1f}%)  P&L: ${pnl:+,.2f}"
                )

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def print_balances(*, output_mode: str) -> None:
    """Print account balances."""
    command = "balance"
    try:
        raw_client = get_authenticated_client()
        client = SchwabClientWrapper(raw_client)
        balances = client.get_account_balances()

        if output_mode == "json":
            print_json_response(command, data={"balances": balances})
            return

        print(f"\n{'=' * 60}")
        print("ACCOUNT BALANCES")
        print(f"{'=' * 60}")

        total_value = 0.0
        total_cash = 0.0

        for balance in balances:
            account_label = balance.get("account", "Account")
            total_value += balance.get("total_value", 0)
            total_cash += balance.get("cash_balance", 0)

            print(
                f"{account_label}: ${balance.get('total_value', 0):>12,.2f} "
                f"(Cash: ${balance.get('cash_balance', 0):>10,.2f})"
            )

        print(f"{'=' * 60}")
        print(f"Total:          ${total_value:>12,.2f} (Cash: ${total_cash:>10,.2f})")
        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def check_auth(*, output_mode: str) -> None:
    """Check authentication status."""
    command = "auth"
    try:
        manager = TokenManager()
        info = manager.get_token_info()

        if output_mode == "json":
            print_json_response(command, data={"token": info})
            return

        print(f"\n{'=' * 60}")
        print("AUTHENTICATION STATUS")
        print(f"{'=' * 60}")
        print(f"Token exists: {info.get('exists', False)}")
        print(f"Token valid:  {info.get('valid', False)}")

        expires_at = info.get("expires") or info.get("expires_at")
        if expires_at:
            print(f"Expires at:   {expires_at}")

        if not info.get("valid", False):
            print("\nRun 'schwab-auth' to authenticate.")

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def show_doctor(*, output_mode: str) -> None:
    """Run diagnostics for configuration and auth."""
    command = "doctor"
    try:
        data_dir = resolve_data_dir()
        portfolio_token_path = resolve_token_path()
        market_token_path = resolve_market_token_path()

        portfolio_creds = {
            "app_key": bool(os.getenv("SCHWAB_INTEL_APP_KEY")),
            "app_secret": bool(os.getenv("SCHWAB_INTEL_CLIENT_SECRET")),
            "callback_url": os.getenv("SCHWAB_INTEL_CALLBACK_URL", "https://127.0.0.1:8001"),
        }
        market_creds = {
            "app_key": bool(os.getenv("SCHWAB_MARKET_APP_KEY")),
            "app_secret": bool(os.getenv("SCHWAB_MARKET_CLIENT_SECRET")),
            "callback_url": os.getenv("SCHWAB_MARKET_CALLBACK_URL", "https://127.0.0.1:8002"),
        }

        portfolio_token = TokenManager(token_path=portfolio_token_path).get_token_info()
        market_token = TokenManager(token_path=market_token_path).get_token_info()

        accounts = secure_config.get_all_accounts()
        accounts_configured = bool(accounts)

        warnings: list[str] = []
        if not (portfolio_creds["app_key"] and portfolio_creds["app_secret"]):
            warnings.append("portfolio_credentials_missing")
        if not portfolio_token.get("exists", False):
            warnings.append("portfolio_token_missing")
        if portfolio_token.get("exists") and not portfolio_token.get("valid", False):
            warnings.append("portfolio_token_invalid")

        if not (market_creds["app_key"] and market_creds["app_secret"]):
            warnings.append("market_credentials_missing")
        if not market_token.get("exists", False):
            warnings.append("market_token_missing")
        if market_token.get("exists") and not market_token.get("valid", False):
            warnings.append("market_token_invalid")

        if not accounts_configured:
            warnings.append("accounts_config_missing")

        data = {
            "data_dir": str(data_dir),
            "portfolio": {
                "credentials_present": portfolio_creds["app_key"] and portfolio_creds["app_secret"],
                "token_path": str(portfolio_token_path),
                "token": portfolio_token,
            },
            "market": {
                "credentials_present": market_creds["app_key"] and market_creds["app_secret"],
                "token_path": str(market_token_path),
                "token": market_token,
            },
            "accounts": {
                "configured": accounts_configured,
                "count": len(accounts),
                "path": str(ACCOUNTS_FILE),
            },
            "warnings": warnings,
        }

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        print(f"\n{'=' * 60}")
        print("SCHWAB CLI DOCTOR")
        print(f"{'=' * 60}")
        print(f"Data directory: {data_dir}")
        print("\nPortfolio API:")
        print(
            f"  Credentials: {'OK' if data['portfolio']['credentials_present'] else 'MISSING'}"
        )
        print(
            f"  Token: {'present' if portfolio_token.get('exists') else 'missing'}"
            f" ({'valid' if portfolio_token.get('valid') else 'invalid'})"
        )
        expires_at = portfolio_token.get("expires") or portfolio_token.get("expires_at")
        if expires_at:
            print(f"  Expires: {expires_at}")
        print(f"  Token path: {portfolio_token_path}")

        print("\nMarket API:")
        print(f"  Credentials: {'OK' if data['market']['credentials_present'] else 'MISSING'}")
        print(
            f"  Token: {'present' if market_token.get('exists') else 'missing'}"
            f" ({'valid' if market_token.get('valid') else 'invalid'})"
        )
        expires_at = market_token.get("expires") or market_token.get("expires_at")
        if expires_at:
            print(f"  Expires: {expires_at}")
        print(f"  Token path: {market_token_path}")

        print("\nAccounts:")
        print(
            f"  Configured: {'yes' if accounts_configured else 'no'}"
            f" ({len(accounts)} accounts)"
        )
        print(f"  Config path: {ACCOUNTS_FILE}")

        if warnings:
            print("\nWarnings:")
            for warning in warnings:
                print(f"  - {warning}")

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def generate_report(
    *,
    output_mode: str,
    output_path: str | None,
    include_market: bool,
) -> None:
    """Generate a portfolio report and save it to disk."""
    command = "report"
    try:
        timestamp = datetime.now()
        raw_client = get_authenticated_client()
        client = SchwabClientWrapper(raw_client)
        accounts = client.get_all_accounts_full()

        summary = build_portfolio_summary(accounts, _account_display_name, MONEY_MARKET_SYMBOLS)
        summary["positions"] = _sanitize_summary_positions(summary.get("positions", []))

        balances = build_account_balances(accounts, _account_display_name, MONEY_MARKET_SYMBOLS)
        allocation = analyze_allocation(accounts)
        performance = build_performance_report(accounts, MONEY_MARKET_SYMBOLS)

        report = {
            "generated_at": timestamp.isoformat(),
            "portfolio": {
                "summary": summary,
                "balances": balances,
                "allocation": allocation,
                "performance": performance,
            },
        }

        warnings: list[str] = []
        if include_market:
            try:
                market_client = resolve_market_client()
                report["market"] = get_market_signals(market_client)
            except Exception as exc:
                warnings.append("market_data_unavailable")
                report["market_error"] = str(exc)

        if warnings:
            report["warnings"] = warnings

        report_path = resolve_report_path(output_path, timestamp=timestamp)
        report_path.write_text(json.dumps(report, indent=2))

        if output_mode == "json":
            print_json_response(command, data={"report_path": str(report_path), "report": report})
            return

        print(f"\n{'=' * 60}")
        print("REPORT SAVED")
        print(f"{'=' * 60}")
        print(f"Path: {report_path}")
        print(f"Total Value: ${summary['total_value']:,.2f}")
        print(f"Total Cash:  ${summary['total_cash']:,.2f}")
        print(f"Positions:   {summary['position_count']}")
        if warnings:
            print(f"Warnings:   {', '.join(warnings)}")
        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)



def list_accounts(*, output_mode: str) -> None:
    """List available account aliases."""
    command = "accounts"
    try:
        accounts = secure_config.get_all_accounts()

        if output_mode == "json":
            account_list = []
            for alias, info in sorted(accounts.items(), key=lambda item: item[0]):
                account_list.append(
                    {
                        "alias": alias,
                        "label": info.label,
                        "name": info.name,
                        "account_type": info.account_type,
                        "tax_status": info.tax_status,
                        "category": info.category,
                        "account_number_masked": secure_config.mask_account_number(
                            info.account_number
                        ),
                        "account_number_last4": info.account_number[-4:],
                        "notes": info.notes,
                        "distribution_deadline": info.distribution_deadline,
                        "beneficiary": info.beneficiary,
                    }
                )
            print_json_response(
                command,
                data={"accounts": account_list, "configured": bool(account_list)},
            )
            return

        print(f"\n{'=' * 60}")
        print("AVAILABLE ACCOUNTS")
        print(f"{'=' * 60}")

        if not accounts:
            print("No accounts configured. See config/accounts.json")
            return

        # Group by category
        by_category: dict[str, list] = {}
        for alias, info in accounts.items():
            cat = info.category
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append((alias, info))

        for category, accts in sorted(by_category.items()):
            print(f"\n{category.upper()}:")
            for alias, info in sorted(accts, key=lambda x: x[0]):
                print(f"  {alias:15s} - {info.label} (...{info.account_number[-4:]})")

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def show_positions(*, symbol: str | None, output_mode: str) -> None:
    """Show positions across accounts."""
    command = "positions"
    try:
        raw_client = get_authenticated_client()
        client = SchwabClientWrapper(raw_client)
        positions = client.get_positions(symbol)

        if output_mode == "json":
            print_json_response(command, data={"positions": positions, "symbol": symbol})
            return

        print(f"\n{'=' * 60}")
        print("POSITIONS")
        print(f"{'=' * 60}")
        if symbol:
            print(f"Filter: {symbol.upper()}")

        if not positions:
            print("No positions found.")
            print()
            return

        for pos in positions:
            sym = pos.get("symbol", "Unknown")
            account = pos.get("account", "Account")
            value = pos.get("market_value", 0)
            pct = pos.get("percentage_of_portfolio", 0)
            pnl = pos.get("unrealized_pl", 0)
            print(
                f"{sym:8s} ${value:>12,.2f} ({pct:5.1f}%)  P&L: ${pnl:+,.2f}  {account}"
            )

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def show_allocation(*, output_mode: str) -> None:
    """Analyze portfolio allocation and concentration."""
    command = "allocation"
    try:
        raw_client = get_authenticated_client()
        client = SchwabClientWrapper(raw_client)
        analysis = client.analyze_allocation()

        if output_mode == "json":
            print_json_response(command, data=analysis)
            return

        print(f"\n{'=' * 60}")
        print("ALLOCATION ANALYSIS")
        print(f"{'=' * 60}")
        print(f"Diversification Score: {analysis['diversification_score']:.2f}")

        print("\nBy Asset Type:")
        for asset_type, info in sorted(analysis.get("by_asset_type", {}).items()):
            value = info.get("value", 0)
            pct = info.get("percentage", 0)
            print(f"  {asset_type:12s} ${value:>12,.2f} ({pct:5.1f}%)")

        risks = analysis.get("concentration_risks", [])
        if risks:
            print("\nConcentration Risks:")
            for risk in risks:
                print(
                    f"  {risk.get('symbol', 'Unknown'):8s} {risk.get('percentage', 0):5.1f}%"
                    f" ({risk.get('risk_level', 'Unknown')})"
                )

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def show_performance(*, output_mode: str) -> None:
    """Show portfolio performance summary."""
    command = "performance"
    try:
        raw_client = get_authenticated_client()
        client = SchwabClientWrapper(raw_client)
        report = client.get_portfolio_performance()

        if output_mode == "json":
            print_json_response(command, data=report)
            return

        print(f"\n{'=' * 60}")
        print("PERFORMANCE")
        print(f"{'=' * 60}")
        print(
            f"Day Change: ${report['daily_change']:+,.2f} "
            f"({report['daily_change_pct']:+.2f}%)"
        )
        print(f"Unrealized P&L: ${report['total_unrealized_pl']:+,.2f}")

        winners = report.get("winners", [])
        losers = report.get("losers", [])

        if winners:
            print("\nTop Winners:")
            for win in winners:
                print(
                    f"  {win.get('symbol', 'Unknown'):8s} "
                    f"${win.get('day_pl', 0):+,.2f}"
                )

        if losers:
            print("\nTop Losers:")
            for loser in losers:
                print(
                    f"  {loser.get('symbol', 'Unknown'):8s} "
                    f"${loser.get('day_pl', 0):+,.2f}"
                )

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def show_vix(*, output_mode: str) -> None:
    """Show VIX data from market API."""
    command = "vix"
    try:
        client = resolve_market_client()
        data = get_vix(client)

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        print(f"\n{'=' * 60}")
        print("VIX")
        print(f"{'=' * 60}")
        print(f"Value: {data['vix']:.2f}")
        print(f"Change: {data['change']:+.2f} ({data['change_pct']:+.2f}%)")
        print(f"Signal: {data['signal']}")
        print(f"Interpretation: {data['interpretation']}")
        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def show_indices(*, output_mode: str) -> None:
    """Show major index quotes."""
    command = "indices"
    try:
        client = resolve_market_client()
        data = get_market_indices(client)

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        print(f"\n{'=' * 60}")
        print("MARKET INDICES")
        print(f"{'=' * 60}")
        for symbol, info in data.get("indices", {}).items():
            print(
                f"{symbol:6s} {info['name']:18s} {info['price']:>10,.2f} "
                f"({info['change_pct']:+.2f}%)"
            )
        print(f"Sentiment: {data.get('sentiment')}")
        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def show_sectors(*, output_mode: str) -> None:
    """Show sector performance and rotation."""
    command = "sectors"
    try:
        client = resolve_market_client()
        data = get_sector_performance(client)

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        print(f"\n{'=' * 60}")
        print("SECTOR PERFORMANCE")
        print(f"{'=' * 60}")
        for sector in data.get("sectors", []):
            print(
                f"{sector['symbol']:4s} {sector['sector']:24s} "
                f"{sector['change_pct']:+.2f}%"
            )

        print(f"\nRotation: {data.get('rotation')}")
        print(f"Leaders: {', '.join(data.get('leaders', []))}")
        print(f"Laggards: {', '.join(data.get('laggards', []))}")
        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def show_market_signals(*, output_mode: str) -> None:
    """Show aggregated market signals."""
    command = "market"
    try:
        client = resolve_market_client()
        data = get_market_signals(client)

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        signals = data.get("signals", {})
        print(f"\n{'=' * 60}")
        print("MARKET SIGNALS")
        print(f"{'=' * 60}")
        print(f"VIX: {signals.get('vix', {}).get('value', 0):.2f} ({signals.get('vix', {}).get('signal')})")
        print(f"Sentiment: {signals.get('market_sentiment')}")
        print(f"Sector Rotation: {signals.get('sector_rotation')}")
        print(f"Overall: {data.get('overall')}")
        print(f"Recommendation: {data.get('recommendation')}")
        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def execute_buy(
    args: list[str],
    *,
    limit_price: float | None,
    dry_run: bool,
    output_mode: str,
    auto_confirm: bool,
    non_interactive: bool,
) -> None:
    """Execute a buy order with confirmation."""
    command = "buy"
    try:
        account, symbol, quantity = parse_trade_args(args, command)
        raw_client = get_authenticated_client()
        client = SchwabClientWrapper(raw_client)

        account_info = secure_config.get_account_info(account)
        if not account_info:
            raise ConfigError(
                f"Unknown account alias '{account}'. Use 'schwab accounts' to see available aliases."
            )

        if limit_price:
            preview = client.buy_limit(account, symbol, quantity, limit_price, dry_run=True)
        else:
            preview = client.buy_market(account, symbol, quantity, dry_run=True)

        if output_mode == "json":
            ensure_trade_confirmation(
                output_mode=output_mode,
                auto_confirm=auto_confirm,
                dry_run=dry_run,
                non_interactive=non_interactive,
            )
            if dry_run:
                print_json_response(command, data={"preview": preview, "submitted": False})
                return

            if limit_price:
                result = client.buy_limit(account, symbol, quantity, limit_price)
            else:
                result = client.buy_market(account, symbol, quantity)

            if not result.get("success"):
                raise PortfolioError(f"Order failed: {result.get('error')}")

            print_json_response(command, data={"preview": preview, "result": result})
            return

        print(f"\n{'=' * 60}")
        print("ORDER PREVIEW")
        print(f"{'=' * 60}")
        print("Action:   BUY")
        print(f"Symbol:   {preview['symbol']}")
        print(f"Quantity: {preview['quantity']} shares")
        if limit_price:
            print(f"Type:     LIMIT @ ${limit_price:.2f}")
        else:
            print("Type:     MARKET")
        print(f"Account:  {preview['account']} ({preview['account_number_masked']})")

        if dry_run:
            print("\n[DRY RUN - Order not submitted]")
            print()
            return

        ensure_trade_confirmation(
            output_mode=output_mode,
            auto_confirm=auto_confirm,
            dry_run=dry_run,
            non_interactive=non_interactive,
        )

        if not auto_confirm:
            print(f"\n{'=' * 60}")
            confirm = input("Execute this order? [y/N]: ").strip().lower()
            if confirm != "y":
                print("Order cancelled.")
                return

        if limit_price:
            result = client.buy_limit(account, symbol, quantity, limit_price)
        else:
            result = client.buy_market(account, symbol, quantity)

        if result.get("success"):
            print("\nOrder submitted successfully!")
            print(f"Order ID: {result.get('order_id')}")
        else:
            raise PortfolioError(f"Order failed: {result.get('error')}")

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def execute_sell(
    args: list[str],
    *,
    limit_price: float | None,
    dry_run: bool,
    output_mode: str,
    auto_confirm: bool,
    non_interactive: bool,
) -> None:
    """Execute a sell order with confirmation."""
    command = "sell"
    try:
        account, symbol, quantity = parse_trade_args(args, command)
        raw_client = get_authenticated_client()
        client = SchwabClientWrapper(raw_client)

        account_info = secure_config.get_account_info(account)
        if not account_info:
            raise ConfigError(
                f"Unknown account alias '{account}'. Use 'schwab accounts' to see available aliases."
            )

        if limit_price:
            preview = client.sell_limit(account, symbol, quantity, limit_price, dry_run=True)
        else:
            preview = client.sell_market(account, symbol, quantity, dry_run=True)

        if output_mode == "json":
            ensure_trade_confirmation(
                output_mode=output_mode,
                auto_confirm=auto_confirm,
                dry_run=dry_run,
                non_interactive=non_interactive,
            )
            if dry_run:
                print_json_response(command, data={"preview": preview, "submitted": False})
                return

            if limit_price:
                result = client.sell_limit(account, symbol, quantity, limit_price)
            else:
                result = client.sell_market(account, symbol, quantity)

            if not result.get("success"):
                raise PortfolioError(f"Order failed: {result.get('error')}")

            print_json_response(command, data={"preview": preview, "result": result})
            return

        print(f"\n{'=' * 60}")
        print("ORDER PREVIEW")
        print(f"{'=' * 60}")
        print("Action:   SELL")
        print(f"Symbol:   {preview['symbol']}")
        print(f"Quantity: {preview['quantity']} shares")
        if limit_price:
            print(f"Type:     LIMIT @ ${limit_price:.2f}")
        else:
            print("Type:     MARKET")
        print(f"Account:  {preview['account']} ({preview['account_number_masked']})")

        if dry_run:
            print("\n[DRY RUN - Order not submitted]")
            print()
            return

        ensure_trade_confirmation(
            output_mode=output_mode,
            auto_confirm=auto_confirm,
            dry_run=dry_run,
            non_interactive=non_interactive,
        )

        if not auto_confirm:
            print(f"\n{'=' * 60}")
            confirm = input("Execute this order? [y/N]: ").strip().lower()
            if confirm != "y":
                print("Order cancelled.")
                return

        if limit_price:
            result = client.sell_limit(account, symbol, quantity, limit_price)
        else:
            result = client.sell_market(account, symbol, quantity)

        if result.get("success"):
            print("\nOrder submitted successfully!")
            print(f"Order ID: {result.get('order_id')}")
        else:
            raise PortfolioError(f"Order failed: {result.get('error')}")

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def show_orders(args: list[str], *, output_mode: str) -> None:
    """Show open orders for an account."""
    command = "orders"
    try:
        account = parse_orders_account(args)
        raw_client = get_authenticated_client()
        client = SchwabClientWrapper(raw_client)

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


def main(args: list | None = None) -> None:
    """Main CLI entry point."""
    common_parser = argparse.ArgumentParser(add_help=False)
    output_group = common_parser.add_mutually_exclusive_group()
    output_group.add_argument("--json", action="store_true", help="Output JSON")
    output_group.add_argument("--text", action="store_true", help="Output text")
    common_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Fail instead of prompting for confirmation",
    )

    parser = argparse.ArgumentParser(
        description="Schwab Portfolio Manager CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common_parser],
        epilog=f"""
Commands:
  portfolio     Show portfolio summary
  positions     Show positions across accounts
  balance       Show account balances
  allocation    Analyze allocation and concentration
  performance   Show daily performance
  vix           Show VIX data
  indices       Show major index quotes
  sectors       Show sector performance
  market        Show aggregated market signals
  auth          Check authentication status
  doctor        Run diagnostics for auth/config
  report        Generate a portfolio report
  accounts      List available account aliases
  buy           Buy shares (market or limit)
  sell          Sell shares (market or limit)
  orders        Show open orders for an account

Defaults:
  - Output defaults to text; set {OUTPUT_ENV_VAR}=json to default JSON output
  - Set {DEFAULT_ACCOUNT_ENV_VAR} to omit ACCOUNT for buy/sell/orders

Examples:
  schwab portfolio                       Show portfolio summary
  schwab portfolio -p                    Show with positions
  schwab positions --symbol AAPL         Filter positions by symbol
  schwab allocation --json               Allocation analysis (JSON)
  schwab performance                     Daily performance
  schwab market --json                   Aggregated market signals
  schwab vix                             VIX interpretation
  schwab doctor                          Auth/config diagnostics
  schwab report                          Save a portfolio report
  schwab accounts                        List account aliases
  schwab buy acct_trading AAPL 10        Market buy
  schwab buy AAPL 10 --yes               Market buy using {DEFAULT_ACCOUNT_ENV_VAR}
  schwab buy AAPL 10 --limit 150 --yes   Limit buy @ $150
  schwab buy AAPL 10 --dry-run           Preview without executing
  schwab sell acct_ira VTI 5 --yes       Market sell
  schwab orders acct_trading             Show open orders
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Portfolio command
    portfolio_parser = subparsers.add_parser(
        "portfolio", help="Show portfolio summary", parents=[common_parser]
    )
    portfolio_parser.add_argument(
        "-p", "--positions", action="store_true", help="Include position details"
    )

    # Balance command
    subparsers.add_parser(
        "balance", help="Show account balances", parents=[common_parser]
    )

    # Auth command
    subparsers.add_parser(
        "auth", help="Check authentication status", parents=[common_parser]
    )

    # Accounts command
    subparsers.add_parser(
        "accounts", help="List available account aliases", parents=[common_parser]
    )

    # Doctor command
    subparsers.add_parser(
        "doctor", help="Run diagnostics", parents=[common_parser]
    )

    # Report command
    report_parser = subparsers.add_parser(
        "report", help="Generate report", parents=[common_parser]
    )
    report_parser.add_argument(
        "--output",
        "-o",
        help="Output path for report JSON (defaults to ~/.schwab-cli-tools/reports)",
    )
    report_parser.add_argument(
        "--no-market",
        action="store_true",
        help="Skip market data in the report",
    )

    # Positions command
    positions_parser = subparsers.add_parser(
        "positions", help="Show positions", parents=[common_parser]
    )
    positions_parser.add_argument("--symbol", help="Filter by symbol")

    # Allocation command
    subparsers.add_parser(
        "allocation", help="Analyze allocation", parents=[common_parser]
    )

    # Performance command
    subparsers.add_parser(
        "performance", help="Show performance", parents=[common_parser]
    )

    # Market data commands
    subparsers.add_parser("vix", help="Show VIX", parents=[common_parser])
    subparsers.add_parser("indices", help="Show indices", parents=[common_parser])
    subparsers.add_parser("sectors", help="Show sectors", parents=[common_parser])
    subparsers.add_parser("market", help="Show market signals", parents=[common_parser])

    # Buy command
    buy_parser = subparsers.add_parser("buy", help="Buy shares", parents=[common_parser])
    buy_parser.add_argument(
        "args",
        nargs="*",
        help=f"[ACCOUNT] SYMBOL QTY (defaults to {DEFAULT_ACCOUNT_ENV_VAR})",
    )
    buy_parser.add_argument("--limit", type=float, help="Limit price (omit for market order)")
    buy_parser.add_argument(
        "--dry-run", action="store_true", help="Preview order without executing"
    )
    buy_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    # Sell command
    sell_parser = subparsers.add_parser("sell", help="Sell shares", parents=[common_parser])
    sell_parser.add_argument(
        "args",
        nargs="*",
        help=f"[ACCOUNT] SYMBOL QTY (defaults to {DEFAULT_ACCOUNT_ENV_VAR})",
    )
    sell_parser.add_argument("--limit", type=float, help="Limit price (omit for market order)")
    sell_parser.add_argument(
        "--dry-run", action="store_true", help="Preview order without executing"
    )
    sell_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    # Orders command
    orders_parser = subparsers.add_parser(
        "orders", help="Show open orders", parents=[common_parser]
    )
    orders_parser.add_argument(
        "args",
        nargs="*",
        help=f"[ACCOUNT] (defaults to {DEFAULT_ACCOUNT_ENV_VAR})",
    )

    parsed = parser.parse_args(args)
    output_mode = resolve_output_mode(parsed)

    if parsed.command == "portfolio":
        print_portfolio(include_positions=parsed.positions, output_mode=output_mode)
    elif parsed.command == "positions":
        show_positions(symbol=parsed.symbol, output_mode=output_mode)
    elif parsed.command == "balance":
        print_balances(output_mode=output_mode)
    elif parsed.command == "allocation":
        show_allocation(output_mode=output_mode)
    elif parsed.command == "performance":
        show_performance(output_mode=output_mode)
    elif parsed.command == "vix":
        show_vix(output_mode=output_mode)
    elif parsed.command == "indices":
        show_indices(output_mode=output_mode)
    elif parsed.command == "sectors":
        show_sectors(output_mode=output_mode)
    elif parsed.command == "market":
        show_market_signals(output_mode=output_mode)
    elif parsed.command == "auth":
        check_auth(output_mode=output_mode)
    elif parsed.command == "doctor":
        show_doctor(output_mode=output_mode)
    elif parsed.command == "report":
        generate_report(
            output_mode=output_mode,
            output_path=parsed.output,
            include_market=not parsed.no_market,
        )
    elif parsed.command == "accounts":
        list_accounts(output_mode=output_mode)
    elif parsed.command == "buy":
        execute_buy(
            parsed.args,
            limit_price=parsed.limit,
            dry_run=parsed.dry_run,
            output_mode=output_mode,
            auto_confirm=parsed.yes,
            non_interactive=parsed.non_interactive,
        )
    elif parsed.command == "sell":
        execute_sell(
            parsed.args,
            limit_price=parsed.limit,
            dry_run=parsed.dry_run,
            output_mode=output_mode,
            auto_confirm=parsed.yes,
            non_interactive=parsed.non_interactive,
        )
    elif parsed.command == "orders":
        show_orders(parsed.args, output_mode=output_mode)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
